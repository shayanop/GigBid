"""Scripted stand-in for the LLM: the `fake` model profile (end-to-end UI tests, demos
without an API key) and the integration tests. Returns schema objects shaped like real
model output, deterministically, so tests check orchestration rather than model quality."""

import re

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableLambda

from agent.handoffs import (
    ClaimCheck,
    ClaimReport,
    ComplianceVerdict,
    Critique,
    FitReport,
    JobSpec,
    LiaisonReply,
    MessageIntent,
    ProposalDraft,
    RequirementMatch,
    RiskReport,
)

FAKE_ID = "fr_ml-p99#0"  # not in the portfolio; the verifier must reject claims citing it
FILLER = "I would start with a short call to confirm scope, data access and milestones. " * 6


class FakeLLM:
    """Stands in for common.ask; returns schema objects shaped like real model output."""

    def __init__(self, critic_rejections=0, fit=0.9, compliance="pass"):
        self.critic_rejections, self.fit, self.verdict = critic_rejections, fit, compliance
        self.calls: list[str] = []

    async def __call__(self, node, schema, user):
        self.calls.append(node)
        return getattr(self, node)(user)

    def analyst(self, user):
        return JobSpec(deliverables=["working system"], skills=["Python"],
                       requirements=["Build the pipeline"], budget="stated", timeline="stated")

    def risk(self, user):
        return RiskReport(score=0.05, flags=[], injection_detected=False, summary="Looks fine.")

    def matcher(self, user):
        first = re.search(r"^\[([^\]]+)\]", user, re.MULTILINE).group(1)
        return FitReport(score=self.fit, reasons=["covers the stack"], matches=[
            RequirementMatch(requirement="Build the pipeline", strength="strong",
                             evidence_ids=[first, "made-up#9"])])

    def writer(self, user):
        evidence_id = re.search(r"^\[([^\]]+)\]", user.split("Evidence:")[1], re.MULTILINE).group(1)
        return ProposalDraft(cover_letter=(
            f"Your team needs answers grounded in its own documents. I built a retrieval "
            f"pipeline for a similar client [{evidence_id}]. I have 15 years of Rust "
            f"experience [{FAKE_ID}]. {FILLER}"))

    def verifier(self, user):
        letter = user.split("Proposal:\n")[1]
        sentences = re.split(r"(?<=[.!?])\s+", letter)
        built = next(s for s in sentences if "retrieval pipeline" in s)
        rust = next((s for s in sentences if "Rust" in s), None)
        claims = [ClaimCheck(sentence=built, claim="built a retrieval pipeline",
                             evidence_ids=[re.search(r"\[([^\]]+)\]", built).group(1)],
                             label="supported")]
        if rust:  # labelled supported by the "model", but cites an id that does not exist
            claims.append(ClaimCheck(sentence=rust, claim="15 years of Rust",
                                     evidence_ids=[FAKE_ID], label="supported"))
        return ClaimReport(claims=claims)

    def critic(self, user):
        reject = self.critic_rejections > 0
        self.critic_rejections -= 1
        return Critique(approve=not reject, issues=["too generic"] * reject,
                        instructions="Be more specific." * reject)

    def compliance(self, user):
        return ComplianceVerdict(status=self.verdict, violations=[],
                                 reason="ok" if self.verdict == "pass" else "fabrication")

    def intent(self, user):
        latest = user.strip().splitlines()[-2].lower()  # last message before the closing tag
        kind = ("interview" if "call" in latest or "interview" in latest
                else "negotiation" if "budget" in latest or "%" in latest else "question")
        return MessageIntent(intent=kind, summary=f"The client sent a {kind}.",
                             asks=["Reply to the client"], injection_detected=False)

    def liaison(self, user):
        pick = " Please pick one of the times below." if "listed under your reply" in user else ""
        return LiaisonReply(body="Thanks for your message. Happy to keep everything here on "
                                 "the platform and to answer anything else." + pick)


def scripted_model(node: str):
    """Runnable with the structured-output contract of config.get_model(node, schema)."""
    fake = FakeLLM()

    def respond(messages):
        parsed = getattr(fake, node)(messages[-1]["content"])
        raw = AIMessage(content="", usage_metadata={"input_tokens": 0, "output_tokens": 0,
                                                    "total_tokens": 0})
        return {"raw": raw, "parsed": parsed, "parsing_error": None}
    return RunnableLambda(respond)
