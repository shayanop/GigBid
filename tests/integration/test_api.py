"""API + worker against real Postgres and Redis, with GigSim, MCP servers and a fake LLM in
process. A burst worker drains the queue the way the deployed worker would."""

import asyncio
import os
from types import SimpleNamespace

import httpx
import pytest
from arq.connections import RedisSettings
from arq.worker import Worker

from apps.api import db, main
from worker import main as worker_main

PASSWORD = "correct horse battery"


@pytest.fixture
async def api(harness, infra):
    toolbox_for = lambda account, trace_id=None: harness.ctx.toolbox

    async def start():
        app = main.create_app()
        app.state.toolbox_for = toolbox_for
        lifespan = main.lifespan(app)
        await lifespan.__aenter__()
        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
        return SimpleNamespace(app=app, client=client, lifespan=lifespan)

    async def stop(server):
        await server.client.aclose()
        await server.lifespan.__aexit__(None, None, None)

    async def drain():
        worker = Worker(functions=[worker_main.run_bid, worker_main.run_conversation,
                                   worker_main.check_inbox], burst=True, handle_signals=False,
                        redis_settings=RedisSettings.from_dsn(os.environ["REDIS_URL"]),
                        on_startup=worker_main.startup, on_shutdown=worker_main.shutdown,
                        ctx={"toolbox_for": toolbox_for}, poll_delay=0.05, max_tries=1)
        await worker.async_run()
        # Worker.close() sends SIGUSR1, which Windows lacks; do its cleanup directly.
        await worker_main.shutdown(worker.ctx)
        await worker.pool.aclose()
        return worker

    server = await start()
    yield SimpleNamespace(server=server, start=start, stop=stop, drain=drain)
    await stop(server)


async def signup(client, email="sana@example.test", account="fr_ml"):
    r = await client.post("/auth/signup", json={"email": email, "password": PASSWORD,
                                                "account": account})
    assert r.status_code == 201, r.text
    return r.json()


async def test_inbox_to_approval_survives_api_restart_and_submits_once(api, harness):
    client = api.server.client
    await signup(client)
    r = await client.post("/jobs", json={"job_id": harness.job(scam=False)},
                          headers={"X-Trace-Id": "trace-test-0001"})
    assert r.status_code == 202 and r.headers["X-Trace-Id"] == "trace-test-0001"
    thread_id = r.json()["thread_id"]
    assert (await client.post("/jobs", json={"job_id": r.json()["job_id"]})).status_code == 409

    await api.drain()
    inbox = (await client.get("/jobs")).json()
    assert inbox[0]["status"] == "awaiting_approval" and inbox[0]["fit"] == 0.9
    detail = (await client.get(f"/jobs/{thread_id}")).json()
    assert detail["draft"]["cover_letter"] and detail["evidence"] and detail["spec"]
    assert (await client.get(f"/runs/{thread_id}")).json()["trace"][0]["node"] == "scout"

    # Restart the API; the pending approval is read back from the Postgres checkpoint.
    await api.stop(api.server)
    api.server = await api.start()
    client = api.server.client
    assert (await client.get("/approvals")).status_code == 401
    r = await client.post("/auth/login", json={"email": "Sana@example.test", "password": PASSWORD})
    assert r.status_code == 200
    review = (await client.get(f"/approvals/{thread_id}")).json()
    assert review["request"]["preview"]["dry_run"] is True
    before = harness.balance()

    assert (await client.post(f"/approvals/{thread_id}", json={"action": "approve"})).status_code == 202
    assert (await client.post(f"/approvals/{thread_id}", json={"action": "approve"})).status_code == 409
    await api.drain()
    job = (await client.get(f"/jobs/{thread_id}")).json()
    assert job["status"] == "submitted"
    assert harness.balance() == before - job["connects_cost"]


async def test_reject_needs_a_reason_and_records_it(api, harness):
    client = api.server.client
    await signup(client)
    thread_id = (await client.post("/jobs", json={"job_id": harness.job(scam=False)})).json()["thread_id"]
    await api.drain()
    assert (await client.post(f"/approvals/{thread_id}", json={"action": "reject"})).status_code == 422
    r = await client.post(f"/approvals/{thread_id}", json={"action": "reject", "reason": "not my niche"})
    assert r.status_code == 202
    await api.drain()
    assert (await client.get(f"/jobs/{thread_id}")).json()["status"] == "rejected"


async def test_weekly_connects_budget_blocks_approval(api, harness):
    client = api.server.client
    await signup(client)
    await client.put("/auth/me/settings", json={"weekly_connects_budget": 1})
    thread_id = (await client.post("/jobs", json={"job_id": harness.job(scam=False)})).json()["thread_id"]
    await api.drain()
    r = await client.post(f"/approvals/{thread_id}", json={"action": "approve"})
    assert r.status_code == 409 and "weekly Connects budget" in r.json()["detail"]


async def test_users_only_see_their_own_threads(api, harness):
    client = api.server.client
    await signup(client)
    thread_id = (await client.post("/jobs", json={"job_id": harness.job(scam=False)})).json()["thread_id"]
    other = httpx.AsyncClient(transport=httpx.ASGITransport(app=api.server.app), base_url="http://t")
    await signup(other, email="other@example.test", account="fr_fs")
    assert (await other.get(f"/jobs/{thread_id}")).status_code == 404
    assert (await other.post(f"/approvals/{thread_id}", json={"action": "approve"})).status_code == 409
    assert (await other.get("/jobs")).json() == []
    await other.aclose()


async def test_saved_search_queues_new_jobs_once_and_skips_reposts(api, harness):
    client = api.server.client
    await signup(client)
    assert (await client.post("/searches", json={"skills": ["LangGraph"], "every_minutes": 5})).status_code == 422
    assert (await client.post("/searches", json={"skills": ["LangGraph"], "every_minutes": 15})).status_code == 201

    worker = SimpleNamespace(ctx={})
    worker.ctx = {"toolbox_for": lambda account, trace_id=None: harness.ctx.toolbox,
                  "redis": api.server.app.state.queue}
    await worker_main.startup(worker.ctx)
    try:
        first = await worker_main.scout_tick(worker.ctx)
        again = await worker_main.scout_tick(worker.ctx)  # not due yet: nothing new
    finally:
        await worker_main.shutdown(worker.ctx)
    titles = [j["title"] for j in (await client.get("/jobs?limit=200")).json()]
    assert first == len(titles) > 0 and again == 0
    queued = {j.job_id for j in await api.server.app.state.queue.queued_jobs()}
    assert len({j for j in queued if j.startswith("bid:")}) == first
    # The same tick checked the inbox: one run per seeded client conversation, once.
    assert len({j for j in queued if j.startswith("conv:")}) == 4


async def test_progress_streams_over_sse(api, harness):
    client = api.server.client
    await signup(client)
    thread_id = (await client.post("/jobs", json={"job_id": harness.job(scam=False)})).json()["thread_id"]
    events = []

    async def listen():
        async with client.stream("GET", f"/runs/{thread_id}/events") as response:
            async for line in response.aiter_lines():
                if line.startswith("event:"):
                    events.append(line.removeprefix("event:").strip())
                    if events[-1] in ("interrupt", "done"):
                        return

    listener = asyncio.create_task(listen())
    await asyncio.sleep(0.5)  # let the subscription start before the worker runs
    await api.drain()
    await asyncio.wait_for(listener, timeout=10)
    assert events[0] == "snapshot" and "node" in events and events[-1] == "interrupt"


async def _approve_and_lose_the_queue(api, harness):
    client = api.server.client
    await signup(client)
    thread_id = (await client.post("/jobs", json={"job_id": harness.job(scam=False)})).json()["thread_id"]
    await api.drain()
    before = harness.balance()
    assert (await client.post(f"/approvals/{thread_id}", json={"action": "approve"})).status_code == 202
    await api.server.app.state.queue.flushdb()  # the queued resume is gone
    return client, thread_id, before


async def _sweep(api, harness, monkeypatch):
    from agent.config import load_config
    monkeypatch.setitem(load_config()["worker"], "orphan_after_minutes", 0)
    ctx = {"toolbox_for": lambda account, trace_id=None: harness.ctx.toolbox,
           "redis": api.server.app.state.queue}
    await worker_main.startup(ctx)
    try:
        await worker_main.scout_tick(ctx)
    finally:
        await worker_main.shutdown(ctx)


async def test_approval_survives_a_lost_queue_entry(api, harness, monkeypatch):
    client, thread_id, before = await _approve_and_lose_the_queue(api, harness)
    await _sweep(api, harness, monkeypatch)  # re-queues the thread stuck in 'processing'
    await api.drain()
    job = (await client.get(f"/jobs/{thread_id}")).json()
    assert job["status"] == "submitted"
    assert harness.balance() == before - job["connects_cost"]


async def test_decision_applied_before_a_crash_is_not_applied_twice(api, harness, monkeypatch):
    client, thread_id, before = await _approve_and_lose_the_queue(api, harness)
    await _sweep(api, harness, monkeypatch)
    await api.drain()
    cost = (await client.get(f"/jobs/{thread_id}")).json()["connects_cost"]
    # Pretend the worker died after resuming the graph but before saving the summary.
    await db.fetchone(api.server.app.state.db, "UPDATE bid_threads SET status = 'processing', "
                      "pending_resume = '{\"action\": \"approve\"}' WHERE id = %s RETURNING id",
                      thread_id)
    await api.server.app.state.queue.enqueue_job("run_bid", thread_id)  # duplicate delivery
    await api.drain()
    assert (await client.get(f"/jobs/{thread_id}")).json()["status"] == "submitted"
    assert harness.balance() == before - cost


async def test_client_messages_get_drafted_replies_and_move_the_pipeline(api, harness):
    client = api.server.client
    await signup(client)
    interview = next(t for t in harness.app.state.data["threads"].values()
                     if t["freelancer_id"] == "fr_ml" and t["_intent"] == "interview")
    await client.post("/jobs", json={"job_id": interview["job_id"]})  # we bid on that job
    assert (await client.post("/messages/refresh")).status_code == 202
    await api.drain()

    conversations = (await client.get("/messages")).json()
    assert len(conversations) == 4
    assert all(c["status"] == "awaiting_approval" for c in conversations)
    conv = next(c for c in conversations if c["conversation_id"] == interview["id"])
    detail = (await client.get(f"/messages/{conv['id']}")).json()
    assert detail["intent"] == "interview" and len(detail["slots"]) == 3
    assert detail["approval_request"]["preview"]["dry_run"] is True
    assert (await client.get("/jobs")).json()[0]["stage"] == "interview"
    assert (await client.get(f"/runs/{conv['id']}")).json()["trace"][0]["node"] == "read"

    assert (await client.post(f"/messages/{conv['id']}", json={"action": "approve"})).status_code == 202
    assert (await client.post(f"/messages/{conv['id']}", json={"action": "approve"})).status_code == 409
    await api.drain()
    assert (await client.get(f"/messages/{conv['id']}")).json()["status"] == "sent"
    assert harness.app.state.data["threads"][interview["id"]]["messages"][-1]["sender"] == "freelancer"
