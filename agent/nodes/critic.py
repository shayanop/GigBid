"""Critic: grounding, personalization and length. Word limits are enforced in code."""

from agent.config import load_config
from agent.handoffs import Critique
from agent.nodes import common


@common.node("critic")
async def review(state: dict) -> dict:
    draft, claims = state["draft"], state["claims"]
    low, high = load_config()["critic"]["min_words"], load_config()["critic"]["max_words"]
    labels = [c.label for c in claims.claims]
    summary = (f"Claim check: {labels.count('supported')} supported, "
               f"{labels.count('partly_supported')} partly supported; unsupported claims were "
               f"removed. Word limits: {low}-{high}.")
    critique = await common.ask("critic", Critique, f"{summary}\n\n"
                                f"{common.job_block(state['job'])}\n\nDraft:\n{draft.cover_letter}")
    words = len(draft.cover_letter.split())
    if not low <= words <= high:
        critique = critique.model_copy(update={
            "approve": False,
            "issues": [*critique.issues, f"{words} words; keep it within {low}-{high}"],
            "instructions": f"{critique.instructions} Make it {low}-{high} words.".strip()})
    return {"critique": critique}
