"""LLM quality judge calibration (B4): agreement between the judge and a human on 30
proposals, as quadratic-weighted Cohen's kappa.

1. Export the items:  uv run python -m evals.runners.judge_calibration export
2. A human fills the human_score column (1 to 5) in evals/datasets/judge_labels.csv.
   Outcomes are left out on purpose so they cannot bias the scoring.
3. Score:             uv run python -m evals.runners.judge_calibration score

The judge is only trusted for proposal quality once kappa is acceptable (0.6 or more is
the usual bar for substantial agreement); disagreements are listed for review.
"""

import argparse
import asyncio
import csv
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from agent.config import load_config
from agent.handoffs import JudgeScore
from agent.nodes import common
from evals.runners.rag_eval import RESULTS, ROOT

LABELS = ROOT / "evals" / "datasets" / "judge_labels.csv"
PERSONAS = ROOT / "data" / "personas"
FIELDS = ["id", "persona", "job_title", "proposal", "human_score"]


def weighted_kappa(a: list[int], b: list[int], categories: int = 5) -> float:
    """Quadratic-weighted Cohen's kappa for two raters on a 1..categories scale."""
    n = len(a)
    observed = [[0.0] * categories for _ in range(categories)]
    for x, y in zip(a, b, strict=True):
        observed[x - 1][y - 1] += 1
    rows = [sum(r) for r in observed]
    cols = [sum(observed[i][j] for i in range(categories)) for j in range(categories)]
    weight = [[(i - j) ** 2 / (categories - 1) ** 2 for j in range(categories)]
              for i in range(categories)]
    disagreement = sum(weight[i][j] * observed[i][j] for i in range(categories)
                       for j in range(categories))
    expected = sum(weight[i][j] * rows[i] * cols[j] / n for i in range(categories)
                   for j in range(categories))
    return 1.0 if expected == 0 else 1 - disagreement / expected


def export(path: Path = LABELS, per_persona: int = 10) -> None:
    """30 past proposals, mixed outcomes, deterministic, without the outcome column."""
    rng, rows = random.Random(30), []
    for persona in ("fr_ml", "fr_fs", "fr_da"):
        lines = (PERSONAS / persona / "proposals.jsonl").read_text(encoding="utf-8").splitlines()
        for item in rng.sample([json.loads(line) for line in lines], per_persona):
            rows.append({"id": item["id"], "persona": persona, "job_title": item["job_title"],
                         "proposal": item["text"], "human_score": ""})
    rng.shuffle(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} items to {path.relative_to(ROOT)}; fill human_score (1-5)")


async def _judge(rows: list[dict]) -> list[JudgeScore]:
    return [await common.ask("judge", JudgeScore, f"Job: {r['job_title']}\n\n"
                             + common.untrusted("proposal", r["proposal"])) for r in rows]


def score(path: Path = LABELS) -> dict:
    with path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    missing = [r["id"] for r in rows if not r["human_score"].strip()]
    if missing:
        sys.exit(f"{len(missing)} items still need a human_score (1-5) in {path}")
    humans = [int(r["human_score"]) for r in rows]
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    judged = asyncio.run(_judge(rows), loop_factory=loop)
    judges = [j.score for j in judged]
    result = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "judge_model": load_config()["profiles"][load_config()["profile"]]
        .get("nodes", {}).get("judge"),
        "items": len(rows),
        "weighted_kappa": round(weighted_kappa(humans, judges), 3),
        "exact_agreement": round(sum(h == j for h, j in zip(humans, judges)) / len(rows), 3),
        "within_one": round(sum(abs(h - j) <= 1 for h, j in zip(humans, judges)) / len(rows), 3),
        "disagreements": [{"id": r["id"], "human": h, "judge": j.score, "judge_reasons": j.reasons,
                           "proposal": r["proposal"]}
                          for r, h, j in zip(rows, humans, judged) if abs(h - j.score) >= 2],
    }
    (RESULTS / "judge_calibration.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("step", choices=["export", "score"])
    args = parser.parse_args()
    if args.step == "export":
        export()
    else:
        result = score()
        print(json.dumps({k: v for k, v in result.items() if k != "disagreements"}, indent=1))
        print(f"{len(result['disagreements'])} items differ by 2 or more points")


if __name__ == "__main__":
    main()
