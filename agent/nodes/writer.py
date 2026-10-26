"""Proposal Writer: evidence-cited cover letter and screening answers. On a revision it
gets the Critic's instructions and its previous draft."""

from agent.handoffs import ProposalDraft
from agent.nodes import common


@common.node("writer")
async def write(state: dict) -> dict:
    spec, price, fit = state["spec"], state["price"], state["fit"]
    cited = {i for m in fit.matches for i in m.evidence_ids}
    evidence = [e for e in state["evidence"] if e.id in cited] or state["evidence"]
    parts = [common.job_block(state["job"]),
             (f"Requirements: {'; '.join(spec.requirements)}\n"
             f"Implicit needs: {'; '.join(spec.implicit_needs) or 'none'}\n"
             f"Screening questions to answer: {spec.screening_questions or 'none'}\n"
             f"Bid: {price.amount:.0f} USD ({price.budget_type})"),
             "Evidence:\n" + common.evidence_block(evidence)]
    critique = state.get("critique")
    revising = bool(critique and not critique.approve)
    if revising:
        parts.append(f"Rewrite your previous draft. Critic instructions: {critique.instructions}"
                     f"\n\nPrevious draft:\n{state['draft'].cover_letter}")
    draft = await common.ask("writer", ProposalDraft, "\n\n".join(parts))
    return {"draft": draft, "revisions": state.get("revisions", 0) + revising}
