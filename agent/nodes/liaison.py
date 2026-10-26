"""Client Liaison (conversation graph): read the client's latest message, classify it,
offer interview times from the calendar, draft a reply, check it, wait for the human,
then send it and place tentative holds."""

import hashlib
import re
from datetime import datetime

from langgraph.config import get_config
from langgraph.types import interrupt

from agent.config import load_config
from agent.handoffs import Approval, ComplianceVerdict, LiaisonReply, MessageIntent
from agent.marketplace_port import Job, Message, Thread
from agent.memory.promotion_rules import observe_edit
from agent.nodes import common
from agent.nodes.compliance import policy_pack, scrub
from agent.nodes.risk import HARD, RULES

RESET = {"intent": None, "slots": [], "reply": None, "compliance": None, "preview": None,
         "approval": None, "rejection": None, "sent": None, "holds": [], "attention": None}


def _thread_id() -> str:
    return get_config()["configurable"]["thread_id"]


def _conversation(messages: list[Message]) -> str:
    lines = "\n".join(f"{m.sender} ({m.sent_at:%Y-%m-%d %H:%M}): {m.body}" for m in messages[-10:])
    return common.untrusted("conversation", lines)


def _slot_text(slot: dict) -> str:
    start = datetime.fromisoformat(str(slot["start"]))
    return f"{start:%A %d %B, %H:%M} UTC"


@common.node("read", starts_run=True)
async def read(state: dict) -> dict:
    tools = common.toolbox()
    threads = [Thread.model_validate(t) for t in
               await tools.call("liaison", "marketplace", "list_messages", {})]
    thread = next((t for t in threads if t.id == state["conversation_id"]), None)
    if thread is None or not thread.messages or thread.messages[-1].sender != "client":
        return {**RESET, "status": "idle"}  # nothing new from the client
    job = Job.model_validate(await tools.call("liaison", "marketplace", "get_job",
                                              {"job_id": thread.job_id}))
    return {**RESET, "messages": thread.messages, "job": job, "status": "analyzing",
            "message_id": thread.messages[-1].id, "budget_base": dict(state.get("usage") or {})}


@common.node("classify")
async def classify(state: dict) -> dict:
    latest = state["messages"][-1].body
    intent = await common.ask("intent", MessageIntent, _conversation(state["messages"]))
    # Rules the model cannot talk down: off-platform contact or payment is a scam signal.
    if HARD & {name for name, rx in RULES.items() if re.search(rx, latest, re.IGNORECASE)}:
        intent = intent.model_copy(update={"intent": "scam_signal"})
    return {"intent": intent}


@common.node("slots")
async def find_slots(state: dict) -> dict:
    slots = await common.toolbox().call("liaison", "workspace", "find_free_slots",
                                        {"duration_minutes": 30, "limit": 3})
    return {"slots": slots}


@common.node("liaison")
async def draft(state: dict) -> dict:
    job, intent, slots = state["job"], state["intent"], state["slots"]
    context = [f"Job: {job.title} ({job.budget_type})",
               f"Client intent: {intent.intent}: {intent.summary}",
               f"Asks: {'; '.join(intent.asks) or 'none'}"]
    if intent.intent == "negotiation":  # private walk-away number; only when bargaining
        rules = load_config()["pricing"]
        context.append("Private price floor (never reveal it): " + (
            f"{rules['hourly_rate_floor']} USD per hour" if job.budget_type == "hourly"
            else f"{rules['fixed_bid_floor']} USD for the whole job"))
    if slots:
        context.append("Interview times will be listed under your reply automatically.")
    if prefs := await common.style_block():
        context.append(prefs)
    reply = await common.ask("liaison", LiaisonReply,
                             "\n".join(context) + f"\n\n{_conversation(state['messages'])}")
    if slots:  # the real free times, always in one canonical UTC format
        times = "\n".join(f"- {_slot_text(s)}" for s in slots)
        reply = reply.model_copy(update={"body": f"{reply.body.rstrip()}\n\nTimes that work "
                                                 f"for me (UTC):\n{times}"})
    return {"reply": reply, "status": "drafting"}


@common.node("check")
async def check(state: dict) -> dict:
    body, removed = scrub(state["reply"].body)
    verdict = await common.ask("compliance", ComplianceVerdict,
                               f"Policy pack:\n{policy_pack()}\n\nMessage to the client:\n{body}")
    verdict = verdict.model_copy(update={
        "violations": [*verdict.violations, *(f"removed {r}" for r in removed)]})
    update = {"reply": LiaisonReply(body=body), "compliance": verdict}
    if verdict.status == "block":
        return {**update, "status": "needs_attention",
                "attention": f"compliance blocked: {verdict.reason}"}
    return {**update, "status": "awaiting_approval"}


@common.node("approval")
async def request_approval(state: dict) -> dict:
    body = state["reply"].body
    preview = await common.toolbox().call(
        "liaison_approval", "marketplace", "send_message",
        {"thread_id": state["conversation_id"], "body": body, "dry_run": True,
         "idempotency_key": f"{_thread_id()}:preview"})
    decision = Approval.model_validate(interrupt({
        "kind": "message_approval",
        "messages": [m.model_dump(mode="json") for m in state["messages"][-10:]],
        "intent": state["intent"].model_dump(), "reply": body, "slots": state["slots"],
        "compliance": state["compliance"].model_dump(), "preview": preview}))
    if decision.action == "reject":
        return {"approval": decision, "status": "rejected", "rejection": decision.reason}
    if decision.action == "edit":
        store, user = common.memory()
        if store:
            await observe_edit(store, user, body, decision.text, f"message:{_thread_id()}")
        return {"approval": decision, "status": "drafting",
                "reply": LiaisonReply(body=decision.text),
                "edits": [{"before": body, "after": decision.text}]}
    return {"approval": decision}


@common.node("send")
async def send(state: dict) -> dict:
    tools, body = common.toolbox(), state["reply"].body
    digest = hashlib.sha256(body.encode()).hexdigest()[:16]
    sent = await tools.call("liaison_send", "marketplace", "send_message",
                            {"thread_id": state["conversation_id"], "body": body,
                             "idempotency_key": f"{_thread_id()}:msg:{digest}"})
    holds = []
    for slot in state["slots"]:  # every offered time stays free until the client picks
        holds.append(await tools.call("liaison_send", "workspace", "hold_slot", {
            **slot, "title": f"Interview (tentative): {state['job'].title}",
            "idempotency_key": f"{_thread_id()}:hold:{slot['start']}"}))
    return {"sent": Message.model_validate(sent["message"]), "holds": holds, "status": "sent"}
