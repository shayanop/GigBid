"""Compliance Guard: rules strip contact details and guarantees, then the model checks
the rest against the policy pack. Runs again after every human edit."""

import re
from functools import cache
from pathlib import Path

from agent.config import load_config
from agent.handoffs import ComplianceVerdict
from agent.nodes import common
from agent.redact import redact

ROOT = Path(__file__).resolve().parents[2]
GUARANTEE = re.compile(r"\bguarantee[sd]?\b|\b100\s?% (?:success|accura|satisf)", re.IGNORECASE)


@cache
def policy_pack() -> str:
    folder = ROOT / load_config()["policy_pack"]
    return "\n\n".join(p.read_text(encoding="utf-8") for p in sorted(folder.glob("*.md")))


def scrub(text: str) -> tuple[str, list[str]]:
    """Drops sentences with contact details or guarantees; returns what was removed."""
    masked = redact(text)
    sentences = re.split(r"(?<=[.!?])\s+", masked)
    contact = [s for s in sentences if "[REDACTED]" in s]
    promises = [s for s in sentences if GUARANTEE.search(s)]
    removed = ["contact details"] * bool(contact) + ["guarantees"] * bool(promises)
    return common.drop_sentences(masked, contact + promises), removed


@common.node("compliance")
async def check(state: dict) -> dict:
    draft = state["draft"]
    letter, removed = scrub(draft.cover_letter)
    answers = [a.model_copy(update={"answer": scrub(a.answer)[0]})
               for a in draft.screening_answers]
    draft = draft.model_copy(update={"cover_letter": letter, "screening_answers": answers})
    body = "\n".join([letter, *(f"Q: {a.question}\nA: {a.answer}" for a in answers)])
    # The Claim Verifier already checked claims against the portfolio; without this the
    # guard sees only the letter and blocks true, specific results as "unverifiable".
    claims = state.get("claims")
    verified = "\n".join(f"- {c.claim} ({c.label.replace('_', ' ')})"
                         for c in (claims.claims if claims else []) if c.label != "unsupported")
    verdict = await common.ask("compliance", ComplianceVerdict,
                               f"Policy pack:\n{policy_pack()}\n\nClaims verified against the "
                               f"freelancer's portfolio evidence:\n{verified or '- none'}\n\n"
                               f"Proposal:\n{body}")
    verdict = verdict.model_copy(update={
        "violations": [*verdict.violations, *(f"removed {r}" for r in removed)]})
    if verdict.status == "block":
        return {"draft": draft, "compliance": verdict, "status": "needs_attention",
                "attention": f"compliance blocked: {verdict.reason}"}
    return {"draft": draft, "compliance": verdict, "status": "awaiting_approval"}
