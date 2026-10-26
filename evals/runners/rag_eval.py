"""Retrieval evaluation (B4): evidence Recall@5, MRR and nDCG@10 per persona.

Evidence is scored per project: each retrieved chunk maps to its project and the
first occurrence sets the project's rank (CV chunks have no project and are
skipped). Labels and graded gains come from evals/datasets/dev_retrieval.jsonl.
Recall@k is capped: hits / min(k, |relevant|), so 1.0 is reachable.

Run: uv run python -m evals.runners.rag_eval --variant v0 [--limit 50]
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

from rag.retriever import build_retriever, rag_config
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
                "recall@5": recall_at_k(ranked, q["relevant"], 5),
                "mrr": mrr(ranked, q["relevant"]),
                "ndcg@10": ndcg_at_k(ranked, q["relevant"], 10)})
    return {
        "variant": variant,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": {"path": DATASET.relative_to(ROOT).as_posix(),
                    "sha256": hashlib.sha256(DATASET.read_bytes()).hexdigest()[:16]},
        "config": rag_config(),
        "overall": _summary([r for rows in scored.values() for r in rows]),
        "per_persona": {p: _summary(rows) for p, rows in scored.items()},
        "per_query": dict(scored),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", default=rag_config()["variant"])
    parser.add_argument("--limit", type=int, help="queries per persona (smoke runs)")
    args = parser.parse_args()
    result = evaluate(args.variant, args.limit)
    RESULTS.mkdir(parents=True, exist_ok=True)
    out = RESULTS / f"rag_{args.variant}.json"
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({"overall": result["overall"], "per_persona": result["per_persona"]},
                     indent=1))
    print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
