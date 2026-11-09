"""Signature extension X3: do code-verified case studies find the skills a project really
used, and do they help retrieval?

Needs the case studies built first (uv run python -m rag.portfolio_builder fr_ml fr_fs fr_da).

1. Skills per repository project against persona_truth.json, micro precision and recall, for
   what each source names: the hand-written case study, the README, the code detector, the
   case study plus the code, and the model's summary before and after verification.
2. Retrieval with and without the verified case studies in the index (deployed pipeline),
   overall and on jobs where at least one relevant project has a repository.

Run: uv run python -m evals.runners.portfolio_builder_eval [--limit 20]
"""

import argparse
import json
import statistics
from datetime import UTC, datetime

from evals.runners.rag_eval import DATASET, RESULTS, ROOT, evaluate
from gigsim.seed import mentioned_skills
from rag.ingest.loaders import SKILLS
from rag.retriever import PERSONAS_DIR, VERIFIED_DIR, rag_config

TRUTH = json.loads((ROOT / "evals" / "datasets" / "persona_truth.json").read_text())
PERSONAS = ("fr_ml", "fr_fs", "fr_da")


def _pr(found: dict[str, set], truth: dict[str, set]) -> dict:
    tp = sum(len(found[p] & truth[p]) for p in truth)
    fp = sum(len(found[p] - truth[p]) for p in truth)
    fn = sum(len(truth[p] - found[p]) for p in truth)
    return {"precision": round(tp / max(tp + fp, 1), 3), "recall": round(tp / max(tp + fn, 1), 3)}


def skill_extraction() -> dict:
    manifests = {p: json.loads((VERIFIED_DIR / p / "manifest.json").read_text(encoding="utf-8"))
                 for p in PERSONAS}
    rows = {project: (persona, m) for persona, ms in manifests.items() for project, m in ms.items()}
    truth = {project: set(TRUTH[project]["skills"]) for project in rows}

    def names(path) -> set:
        return set(mentioned_skills(path.read_text(encoding="utf-8"), SKILLS)) if path.exists() \
            else set()
    case = {pr: names(PERSONAS_DIR / pe / "case_studies" / f"{pr}.md") for pr, (pe, _) in rows.items()}
    readme = {pr: names(PERSONAS_DIR / pe / "repos" / pr / "README.md") for pr, (pe, _) in rows.items()}
    code = {pr: set(m["detected"]) for pr, (_, m) in rows.items()}
    before = {pr: set(m["mentioned_before"]) for pr, (_, m) in rows.items()}
    after = {pr: set(m["mentioned_after"]) for pr, (_, m) in rows.items()}
    unbacked = sum(len(before[p] - code[p]) for p in rows)
    return {
        "repositories": len(rows),
        "sources": {"hand-written case study": _pr(case, truth), "README": _pr(readme, truth),
                    "code detector": _pr(code, truth),
                    "case study + code detector": _pr({p: case[p] | code[p] for p in rows}, truth),
                    "model summary, before verification": _pr(before, truth),
                    "model summary, after verification": _pr(after, truth)},
        "model_mentions_without_code_evidence": unbacked,
        "sentences_dropped": sum(len(m["dropped_sentences"]) for _, m in rows.values()),
        "implied_skills_recovered": sum(len((truth[p] - case[p]) & code[p]) for p in rows),
        "implied_skills_total": sum(len(truth[p] - case[p]) for p in rows),
    }


def _subset(result: dict, keep: set[str]) -> dict:
    rows = [r for qs in result["per_query"].values() for r in qs if r["job_id"] in keep]
    return {"n": len(rows), **{m: round(statistics.mean(r[m] for r in rows), 4)
                               for m in ("recall@5", "mrr", "ndcg@10")}}


def retrieval(limit: int | None) -> dict:
    repo_projects = {d.name for p in PERSONAS for d in (PERSONAS_DIR / p / "repos").iterdir()}
    queries = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    with_repo = {q["job_id"] for q in queries if repo_projects & q["relevant"].keys()}
    cfg, out = rag_config(), {}
    original = cfg.get("verified_case_studies", False)
    try:
        for label, on in (("without", False), ("with", True)):
            cfg["verified_case_studies"] = on  # read by rag.variants.v0_naive.build
            result = evaluate("selected", limit)
            out[label] = {"overall": result["overall"],
                          "jobs with a repository project": _subset(result, with_repo),
                          "per_persona": result["per_persona"]}
    finally:
        cfg["verified_case_studies"] = original
    return out


def table(skills: dict, ret: dict) -> str:
    lines = ["| Source | Precision | Recall |", "| --- | --- | --- |"]
    lines += [f"| {k} | {v['precision']:.3f} | {v['recall']:.3f} |"
              for k, v in skills["sources"].items()]
    lines += ["", "| Index | Recall@5 | MRR | nDCG@10 | Recall@5, jobs with a repo project | p95 ms |",
              "| --- | --- | --- | --- | --- | --- |"]
    for label, r in ret.items():
        o, sub = r["overall"], r["jobs with a repository project"]
        lines.append(f"| {label} verified case studies | {o['recall@5']:.3f} | {o['mrr']:.3f} | "
                     f"{o['ndcg@10']:.3f} | {sub['recall@5']:.3f} (n={sub['n']}) | "
                     f"{o['p95_latency_ms']:.0f} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, help="queries per persona (smoke runs)")
    args = parser.parse_args()
    skills, ret = skill_extraction(), retrieval(args.limit)
    result = {"generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
              "skill_extraction": skills, "retrieval": ret}
    (RESULTS / "portfolio_builder.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    (RESULTS / "portfolio_builder.md").write_text(table(skills, ret), encoding="utf-8")
    print(table(skills, ret))
    print({k: v for k, v in skills.items() if k != "sources"})


if __name__ == "__main__":
    main()
