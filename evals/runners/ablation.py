"""Ablation (B6): the selected pipeline, then the same pipeline with each component
removed in turn, on the full dev set. A component earns its place if removing it hurts.

Run: uv run python -m evals.runners.ablation [--components hybrid+rerank+outcome]
     (defaults to rag.components, the deployed pipeline)
"""

import argparse
import json

from evals.runners.rag_eval import RESULTS, comparison_table, evaluate
from rag.retriever import rag_config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--components", help="e.g. hybrid+rerank; default: rag.components")
    parser.add_argument("--limit", type=int, help="queries per persona (smoke runs)")
    args = parser.parse_args()
    parts = (args.components.split("+") if args.components
             else [name for name, on in rag_config()["components"].items() if on])
    runs = [("v0", "v0"), ("selected", "custom:" + "+".join(parts))]
    runs += [(f"without {p}", "custom:" + "+".join(q for q in parts if q != p)) for p in parts]
    results = []
    for label, variant in runs:
        result = evaluate("v0" if variant == "custom:" else variant, args.limit)
        result["variant"] = label
        print(label, json.dumps(result["overall"]))
        results.append(result)
    (RESULTS / "ablation.json").write_text(json.dumps(
        [{k: r[k] for k in ("variant", "components", "overall", "per_persona", "per_job_type")}
         for r in results], indent=1), encoding="utf-8")
    table = comparison_table(results)
    (RESULTS / "ablation.md").write_text(table, encoding="utf-8")
    print(table)


if __name__ == "__main__":
    main()
