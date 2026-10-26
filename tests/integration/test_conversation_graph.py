"""Conversation graph against in-process GigSim, Marketplace and Workspace MCP servers,
with the scripted fake model."""

from langgraph.types import Command

from agent.graphs import conversation_graph
from mcp_servers.workspace import server as workspace


def thread_with(harness, intent: str) -> str:
    return next(t["id"] for t in harness.app.state.data["threads"].values()
                if t["freelancer_id"] == "fr_ml" and t["_intent"] == intent)


async def run(harness, payload, conversation_id: str):
    graph = conversation_graph.build(harness.saver)
    cfg = {"configurable": {"thread_id": f"conv-{conversation_id}"}}
    await graph.ainvoke(payload, cfg, context=harness.ctx)
    return await graph.aget_state(cfg)


def gigsim_thread(harness, conversation_id: str) -> dict:
    return harness.app.state.data["threads"][conversation_id]


async def test_interview_request_offers_free_times_and_holds_them_after_approval(harness):
    cid = thread_with(harness, "interview")
    snap = await run(harness, {"conversation_id": cid}, cid)
    s = snap.values
    assert snap.next == ("approval",), (s.get("status"), s.get("attention"))
    assert s["intent"].intent == "interview" and len(s["slots"]) == 3
    request = snap.tasks[0].interrupts[0].value
    assert request["kind"] == "message_approval" and request["preview"]["dry_run"]
    assert "UTC" in request["reply"]

    snap = await run(harness, Command(resume={"action": "approve"}), cid)
    assert snap.values["status"] == "sent"
    assert gigsim_thread(harness, cid)["messages"][-1]["sender"] == "freelancer"
    holds = [e for e in workspace._load("fr_ml")["events"] if e["status"] == "tentative"]
    assert len(holds) == 3 and all("Interview (tentative)" in e["title"] for e in holds)


async def test_off_platform_request_is_a_scam_signal_whatever_the_model_says(harness):
    cid = thread_with(harness, "scam")  # "Let's move this to WhatsApp ..."
    snap = await run(harness, {"conversation_id": cid}, cid)
    assert snap.values["intent"].intent == "scam_signal"
    assert "platform" in snap.values["reply"].body and snap.next == ("approval",)


async def test_rejected_reply_sends_nothing(harness):
    cid = thread_with(harness, "question")
    await run(harness, {"conversation_id": cid}, cid)
    snap = await run(harness, Command(resume={"action": "reject", "reason": "I'll call them"}), cid)
    assert snap.values["status"] == "rejected"
    assert gigsim_thread(harness, cid)["messages"][-1]["sender"] == "client"


async def test_each_new_client_message_is_a_new_run_with_its_own_budget(harness, monkeypatch):
    cid = thread_with(harness, "question")
    await run(harness, {"conversation_id": cid}, cid)
    await run(harness, Command(resume={"action": "approve"}), cid)
    first_steps = len((await run(harness, None, cid)).values["trace"])

    from agent.config import load_config
    monkeypatch.setitem(load_config()["budgets"], "max_steps", first_steps)  # would be spent
    gigsim_thread(harness, cid)["messages"].append(
        {"id": f"{cid}_m9", "sender": "client", "body": "Great. Can we do a call?",
         "sent_at": "2026-10-27T10:00:00+00:00"})
    snap = await run(harness, {"conversation_id": cid}, cid)
    assert snap.values["message_id"] == f"{cid}_m9" and snap.next == ("approval",)
    assert snap.values["intent"].intent == "interview" and snap.values["sent"] is None


async def test_nothing_to_answer_when_the_freelancer_spoke_last(harness):
    cid = thread_with(harness, "negotiation")
    gigsim_thread(harness, cid)["messages"].append(
        {"id": f"{cid}_m2", "sender": "freelancer", "body": "Thanks!",
         "sent_at": "2026-10-27T10:00:00+00:00"})
    snap = await run(harness, {"conversation_id": cid}, cid)
    assert snap.values["status"] == "idle" and "classify" not in [t["node"] for t in snap.values["trace"]]



async def test_reply_lists_free_times_once_and_keeps_the_price_floor_private(harness, monkeypatch):
    prompts = []
    fake = harness.fake

    async def spy(node, schema, user):
        prompts.append((node, user))
        return await fake(node, schema, user)
    monkeypatch.setattr("agent.nodes.common.ask", spy)
    cid = thread_with(harness, "interview")
    s = (await run(harness, {"conversation_id": cid}, cid)).values
    liaison_prompt = next(u for n, u in prompts if n == "liaison")
    assert "floor" not in liaison_prompt.lower()  # not a negotiation: no price at all
    assert s["reply"].body.count("Times that work for me") == 1
    assert all(f"{s_['start'][11:16]} UTC" in s["reply"].body for s_ in s["slots"])
