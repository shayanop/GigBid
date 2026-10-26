"""Marketplace MCP tools over an in-memory MCP client, backed by an in-process GigSim."""

import json

import httpx
import pytest
from mcp import Client

from agent.marketplace_port import MarketplaceError
from gigsim.app import create_app
from mcp_servers.marketplace import server
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter


@pytest.fixture
def audit(monkeypatch, tmp_path):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("MARKETPLACE_LOCAL_USER", "fr_ml")
    monkeypatch.setenv("MARKETPLACE_AUDIT_LOG", str(path))
    server._calls.clear()
    return path


@pytest.fixture
def gigsim(monkeypatch, audit):
    app = create_app(n_jobs=200)
    monkeypatch.setattr(server, "adapter_for", lambda user: GigSimAdapter(
        "http://gigsim", user, transport=httpx.ASGITransport(app=app), backoff=0))
    return app


async def call(tool: str, **args):
    async with Client(server.mcp) as client:
        return await client.call_tool(tool, args)


async def test_reads_hide_ground_truth(gigsim):
    page = (await call("search_jobs", skills=["Python"], limit=5)).structured_content
    assert page["total"] > 0 and len(page["jobs"]) == 5
    assert all("Python" in j["skills"] for j in page["jobs"])
    job = (await call("get_job", job_id=page["jobs"][0]["id"])).structured_content
    assert "_truth" not in job
    client = (await call("get_client_history", client_id=job["client_id"])).structured_content
    assert "_prefs" not in client


async def test_submit_spends_connects_exactly_once(gigsim):
    job_id = (await call("search_jobs", limit=1)).structured_content["jobs"][0]["id"]
    draft = {"job_id": job_id, "cover_letter": "Hello", "bid_amount": 500, "idempotency_key": "draft-0001"}

    preview = (await call("create_proposal_draft", **draft, dry_run=True)).structured_content
    assert preview["proposal"] is None and preview["connects_balance"] == 120
    pid = (await call("create_proposal_draft", **draft)).structured_content["proposal"]["id"]
    cost = preview["connects_cost"]

    dry = (await call("submit_proposal", proposal_id=pid, idempotency_key="submit-001",
                      dry_run=True)).structured_content
    assert dry["connects_balance_after"] == 120 - cost
    assert (await call("get_connects_balance")).structured_content["balance"] == 120

    for _ in range(2):  # a retried submit with the same key must not charge twice
        done = await call("submit_proposal", proposal_id=pid, idempotency_key="submit-001")
        assert done.structured_content["proposal"]["status"] == "submitted"
    assert (await call("get_connects_balance")).structured_content["balance"] == 120 - cost

    again = await call("submit_proposal", proposal_id=pid, idempotency_key="submit-002")
    assert again.is_error and "already submitted" in again.content[0].text


async def test_idempotency_key_reuse_with_other_payload_is_refused(gigsim):
    adapter = server.adapter_for("fr_ml")
    with pytest.raises(MarketplaceError, match="422"):
        for body in ("first", "second"):
            await adapter.send_message("th_0001", body, "msg-key-01")


async def test_invalid_input_is_rejected(gigsim):
    assert (await call("search_jobs", limit=500)).is_error
    assert (await call("get_job", job_id="../etc/passwd")).is_error
    assert (await call("create_proposal_draft", job_id="job_00001", cover_letter="x",
                       bid_amount=-5, idempotency_key="draft-0002")).is_error


async def test_retries_outages_then_succeeds():
    replies = iter([httpx.Response(503), httpx.Response(429, headers={"Retry-After": "0"}),
                    httpx.Response(200, json={"balance": 7})])
    adapter = GigSimAdapter("http://gigsim", "fr_ml", backoff=0,
                            transport=httpx.MockTransport(lambda request: next(replies)))
    assert await adapter.get_connects() == 7


async def test_unreachable_marketplace_reports_degraded_state(monkeypatch, audit):
    def down(request):
        raise httpx.ConnectError("connection refused")
    monkeypatch.setattr(server, "adapter_for", lambda user: GigSimAdapter(
        "http://gigsim", user, transport=httpx.MockTransport(down), backoff=0))
    result = await call("get_connects_balance")
    assert result.is_error and "marketplace unavailable" in result.content[0].text


async def test_per_user_rate_limit(gigsim, monkeypatch):
    monkeypatch.setenv("MARKETPLACE_RATE_PER_MIN", "2")
    results = [await call("get_connects_balance") for _ in range(3)]
    assert [r.is_error for r in results] == [False, False, True]


async def test_audit_log_records_calls_without_pii(gigsim, audit):
    await call("send_message", thread_id="th_0001", body="Reach me at sana@example.com",
               idempotency_key="msg-key-02")
    record = json.loads(audit.read_text().splitlines()[-1])
    assert record["user"] == "fr_ml" and record["tool"] == "send_message" and record["trace_id"]
    assert "sana@example.com" not in json.dumps(record)
