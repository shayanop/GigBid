"""Risk Assessor: client history + rule flags + LLM judgement -> RiskReport.
Rule hits set a floor on the score that the model cannot talk down."""

import re

from agent.handoffs import RiskReport
from agent.marketplace_port import Client
from agent.nodes import common

RULES = {
    "off_platform_contact": r"telegram|whatsapp|skype|wechat|contact me (?:at|on|via)",
    "off_platform_payment": (r"crypto|bitcoin|usdt|outside the platform|avoid (?:the )?fees"
                             r"|pay you directly"),
    "free_work": r"\bfree (?:sample|test|trial)\b|\bfor free\b|\bunpaid\b",
    "sensitive_data": r"bank (?:account|details)|photo of your id|passport|social security",
    "prompt_injection": (r"ignore (?:all )?(?:previous|prior) instructions"
                         r"|\bai (?:assistants?|agents?)\b|^\s*system\s*:|pre-approved"),
}
HARD = {"off_platform_contact", "off_platform_payment", "free_work", "sensitive_data"}
FACT_FLAGS = {"unverified_client", "no_spend_history"}


def rule_flags(text: str, client: Client) -> list[str]:
    flags = [name for name, rx in RULES.items() if re.search(rx, text, re.IGNORECASE | re.MULTILINE)]
    if not client.payment_verified:
        flags.append("unverified_client")
    if client.total_spend == 0 and client.jobs_posted <= 3:
        flags.append("no_spend_history")
    return flags


@common.node("risk")
async def assess(state: dict) -> dict:
    job = state["job"]
    client = Client.model_validate(await common.toolbox().call(
        "risk", "marketplace", "get_client_history", {"client_id": job.client_id}))
    flags = rule_flags(f"{job.title}\n{job.description}", client)
    history = (f"Client: payment verified {client.payment_verified}, total spend "
               f"{client.total_spend:.0f} USD, hire rate {client.hire_rate:.0%}, "
               f"{client.jobs_posted} jobs posted, rating {client.rating}, member since "
               f"{client.member_since:%Y-%m}.\nRule flags: {', '.join(flags) or 'none'}\n")
    report = await common.ask("risk", RiskReport, history + common.job_block(job))
    floor = 0.8 if HARD & set(flags) else 0.3 if "unverified_client" in flags else 0.0
    # Facts from client history belong to the rules; the model has invented them before.
    model_flags = {f for f in report.flags if f not in FACT_FLAGS}
    report = report.model_copy(update={
        "score": max(report.score, floor), "flags": sorted(model_flags | set(flags)),
        "injection_detected": report.injection_detected or "prompt_injection" in flags})
    return {"risk": report, "client": client}
