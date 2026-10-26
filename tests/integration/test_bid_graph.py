"""Bid graph end to end against in-process GigSim and both MCP servers. The LLM is a
scripted fake, so these tests check orchestration, not model quality."""

import asyncio
import os

import httpx
import pytest
from langgraph.types import Command

from agent.config import load_config
from agent.graphs import bid_graph
from agent.mcp_client import Toolbox
from agent.nodes import common
from mcp_servers.marketplace import server as marketplace
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from rag import retriever


async def run(h, payload, graph=None):
    graph = graph or bid_graph.build(h.saver)
    await graph.ainvoke(payload, h.cfg, context=h.ctx)
    return await graph.aget_state(h.cfg)


def nodes(state) -> list[str]:
    return [t["node"] for t in state.values["trace"]]


async def test_bid_revises_at_most_twice_pauses_for_approval_and_survives_restart(harness):
    harness.fake.critic_rejections = 5  # critic never satisfied; the loop must still end
    snap = await run(harness, {"job_id": harness.job(scam=False)})
    s = snap.values
    assert snap.next == ("approval",), (s.get("status"), s.get("attention"), nodes(snap))
    assert s["status"] == "awaiting_approval"
    assert nodes(snap).count("decide") == 1  # parallel branches joined once
    assert {"analyst", "risk", "matcher"} <= set(nodes(snap)[1:4])
    assert s["revisions"] == 2 and nodes(snap).count("writer") == 3
    assert "Rust" not in s["draft"].cover_letter  # unsupported claim removed before critic
    assert [c.claim for c in s["claims"].unsupported] == ["15 years of Rust"]
    assert all("made-up#9" not in m.evidence_ids for m in s["fit"].matches)

    request = snap.tasks[0].interrupts[0].value
    assert request["preview"]["dry_run"] and request["preview"]["proposal"] is None
    assert request["claims"][0]["evidence"] and request["price"]["rationale"]
    before = harness.balance()

    # "Restart": a fresh graph object resumes from the checkpoint alone.
    done = await run(harness, Command(resume={"action": "approve"}), bid_graph.build(harness.saver))
    assert done.values["status"] == "submitted" and done.next == ()
    assert harness.balance() == before - done.values["submission"].connects_cost


async def test_scam_job_is_skipped_by_rules_even_when_the_model_says_safe(harness):
    snap = await run(harness, {"job_id": harness.job(scam=True)})
    s = snap.values
    assert s["status"] == "skipped" and s["decision"].action == "skip"
    assert s["risk"].score >= 0.8 and "writer" not in harness.fake.calls


async def test_low_fit_is_watched_not_drafted(harness):
    harness.fake.fit = 0.6
    snap = await run(harness, {"job_id": harness.job(scam=False)})
    assert snap.values["status"] == "watching" and "writer" not in harness.fake.calls


async def test_reject_records_reason_and_sends_nothing(harness):
    await run(harness, {"job_id": harness.job(scam=False)})
    before = harness.balance()
    snap = await run(harness, Command(resume={"action": "reject", "reason": "too far from my niche"}))
    assert snap.values["status"] == "rejected"
    assert snap.values["rejection"] == "too far from my niche" and harness.balance() == before


async def test_edit_is_rechecked_by_compliance_and_diff_is_kept(harness):
    await run(harness, {"job_id": harness.job(scam=False)})
    edited = f"Happy to help with this. Email me at sana@example.com. {harness.filler}"
    snap = await run(harness, Command(resume={"action": "edit", "text": edited}))
    s = snap.values
    assert snap.next == ("approval",)  # back for a second look after compliance
    assert "sana@example.com" not in s["draft"].cover_letter
    assert "removed contact details" in s["compliance"].violations
    assert s["edits"][0]["after"] == edited and "+Happy to help" in s["edits"][0]["diff"]
    assert nodes(snap).count("compliance") == 2

    snap = await run(harness, Command(resume={"action": "approve"}))
    assert snap.values["status"] == "submitted"


async def test_compliance_block_needs_attention(harness):
    harness.fake.verdict = "block"
    snap = await run(harness, {"job_id": harness.job(scam=False)})
    assert snap.values["status"] == "needs_attention" and snap.next == ()
    assert "compliance blocked" in snap.values["attention"]


async def test_budget_exhaustion_needs_attention(harness, monkeypatch):
    monkeypatch.setitem(load_config()["budgets"], "max_steps", 6)
    snap = await run(harness, {"job_id": harness.job(scam=False)})
    assert snap.values["status"] == "needs_attention"
    assert "budget exhausted" in snap.values["attention"] and "writer" not in nodes(snap)


async def test_marketplace_outage_dead_letters_the_thread(harness, monkeypatch):
    def down(request):
        raise httpx.ConnectError("refused")
    monkeypatch.setattr(marketplace, "adapter_for", lambda user: GigSimAdapter(
        "http://gigsim", user, transport=httpx.MockTransport(down), backoff=0))
    snap = await run(harness, {"job_id": harness.job(scam=False)})
    assert snap.values["status"] == "needs_attention"
    assert "ToolUnavailable" in snap.values["attention"]


async def test_failure_in_a_parallel_branch_needs_attention_instead_of_crashing(
        harness, monkeypatch):
    def broken(persona, variant=None):
        raise RuntimeError("index unreadable")
    monkeypatch.setattr(retriever, "get_retriever", broken)
    snap = await run(harness, {"job_id": harness.job(scam=False)})
    assert snap.values["status"] == "needs_attention" and snap.next == ()
    assert snap.values["attention"].startswith("matcher failed: ToolCallError")
    assert "pricing" not in nodes(snap)


async def test_crash_after_submit_retries_without_double_charge(harness, monkeypatch):
    await run(harness, {"job_id": harness.job(scam=False)})
    before, original, crashed = harness.balance(), Toolbox.call, []

    async def flaky(self, agent, server, tool, args):
        result = await original(self, agent, server, tool, args)
        if tool == "submit_proposal" and not crashed:
            crashed.append(1)
            raise ConnectionError("worker died before saving the checkpoint")
        return result
    monkeypatch.setattr(Toolbox, "call", flaky)
    snap = await run(harness, Command(resume={"action": "approve"}))
    assert crashed and snap.values["status"] == "submitted"
    assert harness.balance() == before - snap.values["submission"].connects_cost


@pytest.mark.postgres
async def test_postgres_checkpoint_survives_restart(harness, infra):
    from agent.graphs.checkpoint import postgres_checkpointer
    harness.cfg["configurable"]["thread_id"] = f"pg-{os.getpid()}"
    async with postgres_checkpointer() as saver:
        harness.saver = saver
        assert (await run(harness, {"job_id": harness.job(scam=False)})).next == ("approval",)
    async with postgres_checkpointer() as saver:  # new connection = restarted API
        harness.saver = saver
        snap = await run(harness, Command(resume={"action": "approve"}))
        assert snap.values["status"] == "submitted"


async def test_slow_parallel_branch_times_out_into_needs_attention(harness, monkeypatch):
    monkeypatch.setitem(load_config()["budgets"], "node_timeout_seconds", 1.0)
    fake = harness.fake

    async def slow_matcher(node, schema, user):
        if node == "matcher":
            await asyncio.sleep(5)
        return await fake(node, schema, user)
    monkeypatch.setattr(common, "ask", slow_matcher)
    snap = await run(harness, {"job_id": harness.job(scam=False)})
    assert snap.values["status"] == "needs_attention"
    assert snap.values["attention"].startswith("matcher failed: TimeoutError")
