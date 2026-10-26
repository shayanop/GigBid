"""Fit Matcher: portfolio evidence per requirement -> FitReport. It runs in parallel with
the analyst, so it searches with the post and the marketplace's skill list."""

import asyncio

from agent.handoffs import FitReport
from agent.nodes import common
from rag.schema import Evidence


@common.node("matcher")
async def match(state: dict) -> dict:
    job, tools = state["job"], common.toolbox()
    queries = [f"{job.title}\n{job.description}"[:2000], *job.skills]
    results = await asyncio.gather(*(tools.call(
        "matcher", "portfolio", "search_evidence", {"requirement": q, "k": 4}) for q in queries))
    found = {e["id"]: Evidence.model_validate(e) for hits in results for e in hits}
    evidence = sorted(found.values(), key=lambda e: -e.score)[:20]
    report = await common.ask("matcher", FitReport, common.job_block(job)
                              + "\n\nEvidence:\n" + common.evidence_block(evidence))
    valid = {e.id for e in evidence}  # drop ids the model invented
    matches = [m.model_copy(update={"evidence_ids": [i for i in m.evidence_ids if i in valid]})
               for m in report.matches]
    return {"fit": report.model_copy(update={"matches": matches}), "evidence": evidence}
