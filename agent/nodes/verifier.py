"""Claim Verifier (B3): labels each claim against the evidence and removes unsupported
ones before the Critic sees the draft. A claim citing no real evidence id is unsupported."""

from agent.handoffs import ClaimReport
from agent.nodes import common


@common.node("verifier")
async def verify(state: dict) -> dict:
    draft, evidence = state["draft"], state["evidence"]
    known = {e.id for e in evidence}
    answers = "\n".join(f"Q: {a.question}\nA: {a.answer}" for a in draft.screening_answers)
    report = await common.ask("verifier", ClaimReport,
                              f"Proposal:\n{draft.cover_letter}\n\nScreening answers:\n"
                              f"{answers or 'none'}\n\nEvidence:\n"
                              + common.evidence_block(evidence))
    claims = [c if c.label == "unsupported" or (c.evidence_ids and set(c.evidence_ids) <= known)
              else c.model_copy(update={"label": "unsupported"}) for c in report.claims]
    report = ClaimReport(claims=claims)
    drop = [c.sentence for c in report.unsupported]
    cleaned = draft.model_copy(update={
        "cover_letter": common.drop_sentences(draft.cover_letter, drop),
        "screening_answers": [
            a.model_copy(update={"answer": common.drop_sentences(a.answer, drop)})
            for a in draft.screening_answers]})
    return {"claims": report, "draft": cleaned}
