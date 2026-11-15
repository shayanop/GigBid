"""Scam detection on real labelled job postings (the fake-jobs dataset, see docs/DATA_CARD.md).

A posting counts as caught when the Risk Assessor's score is above decision.bid_max_risk, i.e.
the bid graph would skip it. Two detectors:
- rules: the regex flags alone (free), on every labelled posting and on the sample;
- risk: rules plus the model (agent.nodes.risk.judge) on a balanced sample.
The dataset has no client histories, so every posting gets the same verified, established
client: only the posting's text can decide. Fakes are split into "templated" (near-identical
generated posts) and "other", because the templated ones are far easier.

Run: uv run python -m evals.runners.scam_eval [--n 60]   (about 1k tokens per posting)
"""

import argparse
import asyncio
import json
import random
import sys
from datetime import UTC, datetime
from pathlib import Path

from agent.config import load_config, profile_name
from agent.marketplace_port import Client, Job
from agent.nodes import risk

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "data" / "processed" / "real" / "scam_real.jsonl"
RESULTS = ROOT / "evals" / "results"
CLIENT = Client(id="eval", name="Established client", country="US", payment_verified=True,
                total_spend=25_000, hire_rate=0.7, jobs_posted=20, rating=4.8, reviews=[],
                member_since=datetime(2020, 1, 1, tzinfo=UTC))


def job(row: dict) -> Job:
    return Job(id=row["id"], title=row["title"], description=row["text"], skills=[],
               budget_type="fixed", budget_min=None, budget_max=None,
               posted_at=datetime(2026, 1, 1, tzinfo=UTC), connects_cost=4, client_id="eval")


def rules_flag(row: dict) -> bool:
    return bool(risk.HARD & set(risk.rule_flags(f"{row['title']}\n{row['text']}", CLIENT)))


def scores(rows: list[dict], predicted: list[bool]) -> dict:
    tp = sum(p and r["fraudulent"] for r, p in zip(rows, predicted, strict=True))
    fp = sum(p and not r["fraudulent"] for r, p in zip(rows, predicted, strict=True))
    fakes, real = sum(r["fraudulent"] for r in rows), sum(not r["fraudulent"] for r in rows)
    precision, recall = tp / max(tp + fp, 1), tp / max(fakes, 1)

    def caught(templated: bool) -> float | None:
        group = [p for r, p in zip(rows, predicted, strict=True)
                 if r["fraudulent"] and r["templated"] == templated]
        return round(sum(group) / len(group), 3) if group else None
    return {"n": len(rows), "precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(2 * precision * recall / max(precision + recall, 1e-9), 3),
            "false_positive_rate": round(fp / max(real, 1), 3),
            "recall_templated_fakes": caught(True), "recall_other_fakes": caught(False)}


def sample(rows: list[dict], n: int, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    pick = lambda pool, k: rng.sample(pool, min(k, len(pool)))
    return (pick([r for r in rows if not r["fraudulent"]], n // 2)
            + pick([r for r in rows if r["fraudulent"] and r["templated"]], n // 4)
            + pick([r for r in rows if r["fraudulent"] and not r["templated"]], n - n // 2 - n // 4))


async def model_flags(rows: list[dict], threshold: float, parallel: int = 3) -> list[dict]:
    gate = asyncio.Semaphore(parallel)

    async def one(row):
        async with gate:
            try:
                report = await risk.judge(job(row), CLIENT)
                return {"id": row["id"], "score": report.score, "flags": report.flags,
                        "caught": report.score > threshold}
            except Exception as e:  # noqa: BLE001 - recorded, not hidden
                return {"id": row["id"], "error": f"{type(e).__name__}: {e}"[:200]}
    return await asyncio.gather(*(one(r) for r in rows))


async def run(n: int) -> dict:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    threshold = load_config()["decision"]["bid_max_risk"]
    picked = sample(rows, n)
    judged = await model_flags(picked, threshold)
    ok = [(r, j) for r, j in zip(picked, judged, strict=True) if "error" not in j]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "profile": profile_name(), "threshold": threshold,
        "rules_all_postings": scores(rows, [rules_flag(r) for r in rows]),
        "rules_sample": scores([r for r, _ in ok], [rules_flag(r) for r, _ in ok]),
        "risk_sample": scores([r for r, _ in ok], [j["caught"] for _, j in ok]),
        "errors": [j for j in judged if "error" in j],
        "per_posting": [dict(j, fraudulent=r["fraudulent"], templated=r["templated"])
                        for r, j in zip(picked, judged, strict=True)],
    }


def table(result: dict) -> str:
    lines = [("| Detector | Postings | Precision | Recall | F1 | False-positive rate | "
             "Recall, templated fakes | Recall, other fakes |"), "| --- " * 8 + "|"]
    for name, key in (("Rules, all labelled postings", "rules_all_postings"),
                      ("Rules, sample", "rules_sample"), ("Rules + model, sample", "risk_sample")):
        s = result[key]
        lines.append(f"| {name} | {s['n']} | {s['precision']:.3f} | {s['recall']:.3f} | "
                     f"{s['f1']:.3f} | {s['false_positive_rate']:.3f} | "
                     f"{s['recall_templated_fakes']} | {s['recall_other_fakes']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=60, help="postings in the model sample")
    args = parser.parse_args()
    load_config()  # loads .env
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    result = asyncio.run(run(args.n), loop_factory=loop)
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "scam_eval.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    (RESULTS / "scam_eval.md").write_text(table(result), encoding="utf-8")
    print(table(result), f"{len(result['errors'])} errors")


if __name__ == "__main__":
    main()
