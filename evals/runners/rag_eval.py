"""Retrieval evaluation (B4): evidence Recall@5, MRR and nDCG@10 per persona.

Evidence is scored per project: each retrieved chunk maps to its project and the
first occurrence sets the project's rank (CV chunks have no project and are
skipped). Labels and graded gains come from evals/datasets/dev_retrieval.jsonl.
Recall@k is capped: hits / min(k, |relevant|), so 1.0 is reachable.

Run: uv run python -m evals.runners.rag_eval --variant v0 v1 v2 v3 v4 v8 --table rag_comparison.md
     (--limit 20 for a smoke run)
"""

import argparse
import hashlib
import json
import math
import statistics
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from rag.retriever import build_retriever, components_for, rag_config
from rag.schema import Evidence

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "evals" / "datasets" / "dev_retrieval.jsonl"
RESULTS = ROOT / "evals" / "results"


def recall_at_k(ranked: list[str], relevant: dict[str, int], k: int) -> float:
    return len(set(ranked[:k]) & relevant.keys()) / min(k, len(relevant))


def mrr(ranked: list[str], relevant: dict[str, int]) -> float:
    return next((1 / i for i, p in enumerate(ranked, 1) if p in relevant), 0.0)


def ndcg_at_k(ranked: list[str], gains: dict[str, int], k: int) -> float:
    dcg = sum(gains.get(p, 0) / math.log2(i + 1) for i, p in enumerate(ranked[:k], 1))
    ideal = sum(g / math.log2(i + 1)
                for i, g in enumerate(sorted(gains.values(), reverse=True)[:k], 1))
    return dcg / ideal if ideal else 0.0


def rank_projects(evidence: list[Evidence]) -> list[str]:
    return list(dict.fromkeys(e.project for e in evidence if e.project))


def _summary(rows: list[dict]) -> dict:
    lat = sorted(r["latency_ms"] for r in rows)
    return {"n": len(rows),
            **{m: round(statistics.mean(r[m] for r in rows), 4)
               for m in ("recall@5", "mrr", "ndcg@10")},
            "p50_latency_ms": round(lat[len(lat) // 2], 1),
            "p95_latency_ms": round(lat[min(len(lat) - 1, math.ceil(0.95 * len(lat)) - 1)], 1)}


def evaluate(variant: str, limit: int | None = None, embedder=None) -> dict:
    queries = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    by_persona = defaultdict(list)
    for q in queries:
        by_persona[q["persona"]].append(q)
    scored = defaultdict(list)
    for persona, rows in by_persona.items():
        index = build_retriever(persona, variant, embedder)
        for q in rows[:limit]:
            start = time.perf_counter()
            ranked = rank_projects(index.search(q["query"], k=100))[:10]
            scored[persona].append({
                "job_id": q["job_id"], "latency_ms": (time.perf_counter() - start) * 1000,
                "skills": len(q["skills"]),
                "recall@5": recall_at_k(ranked, q["relevant"], 5),
                "mrr": mrr(ranked, q["relevant"]),
                "ndcg@10": ndcg_at_k(ranked, q["relevant"], 10)})
    every = [r for rows in scored.values() for r in rows]
    return {
        "variant": variant,
        "components": components_for(variant).on(),
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": {"path": DATASET.relative_to(ROOT).as_posix(),
                    "sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest()[:16]},
        "config": rag_config(),
        "overall": _summary(every),
        "per_persona": {p: _summary(rows) for p, rows in scored.items()},
        # The hypothesis is about jobs with several distinct requirements.
        "per_job_type": {"4+ skills": _summary([r for r in every if r["skills"] >= 4]),
                         "under 4 skills": _summary([r for r in every if r["skills"] < 4])},
        "per_query": dict(scored),
    }


def comparison_table(results: list[dict], baseline: str = "v0") -> str:
    """Markdown table of variants against the baseline (B5)."""
    base = next((r for r in results if r["variant"] == baseline), results[0])["overall"]
    lines = [("| Variant | Components | Recall@5 | MRR | nDCG@10 | Recall@5, 4+ skills | "
              "p95 latency (ms) |"), "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in results:
        o, hard = r["overall"], r["per_job_type"]["4+ skills"]
        delta = o["recall@5"] - base["recall@5"]
        lines.append(f"| {r['variant']} | {', '.join(r['components']) or 'dense only'} | "
                     f"{o['recall@5']:.3f} ({delta:+.3f}) | {o['mrr']:.3f} | {o['ndcg@10']:.3f} | "
                     f"{hard['recall@5']:.3f} | {o['p95_latency_ms']:.0f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", nargs="+", default=[rag_config()["variant"]],
                        help="one or more: v0 v1 v2 v3 v4 v8 selected custom:hybrid+rerank")
    parser.add_argument("--limit", type=int, help="queries per persona (smoke runs)")
    parser.add_argument("--table", help="also write a markdown comparison to this results file")
    args = parser.parse_args()
    RESULTS.mkdir(parents=True, exist_ok=True)
    results = []
    for variant in args.variant:
        result = evaluate(variant, args.limit)
        name = variant.replace(":", "_").replace("+", "_")
        (RESULTS / f"rag_{name}.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        print(variant, json.dumps(result["overall"]))
        results.append(result)
    if args.table:
        (RESULTS / args.table).write_text(comparison_table(results), encoding="utf-8")
        print(comparison_table(results))


if __name__ == "__main__":
    main()
