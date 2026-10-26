"""Arq worker (E1): scheduled scouting and every graph run; web handlers only queue work.

Each run decides what to do from durable state (the bid_threads row and the graph
checkpoint), never from the queue message, so lost or duplicated queue entries are safe:
- a thread exists once per (user, job id) and per (user, content hash): reposts and
  repeated searches are never analyzed twice;
- a human decision is stored on the thread (pending_resume) before it is queued, and is
  applied only while the graph is still waiting for it;
- a run that died mid-graph continues from its last checkpoint;
- one run per thread at a time (Redis lock); marketplace writes carry idempotency keys;
- every tick re-queues threads whose queue entry was lost.

Run: uv run python -m worker.main
"""

import asyncio
import logging
import os
import sys
import time
from datetime import timedelta

from arq import Retry, cron
from arq.connections import RedisSettings
from arq.worker import Worker, run_worker
from dotenv import load_dotenv
from langgraph.types import Command

from agent.config import load_config
from agent.graphs import bid_graph
from agent.graphs.checkpoint import postgres_checkpointer
from agent.mcp_client import Toolbox, ToolCallError
from agent.nodes.common import Context
from apps.api import db, streaming

load_dotenv()
log = logging.getLogger("gigbid.worker")
JOB_TIMEOUT = 900  # a full bid run with rate-limit waits takes minutes
# Failures worth replaying later: the dependency or the model provider may recover.
TRANSIENT = ("ToolUnavailable", "RateLimitError", "Timeout", "APIConnectionError",
             "InternalServerError")


async def startup(ctx: dict) -> None:
    ctx["db"] = await db.open_pool()
    ctx["saver"] = postgres_checkpointer()
    ctx["graph"] = bid_graph.build(await ctx["saver"].__aenter__())
    ctx.setdefault("toolbox_for", Toolbox.for_user)


async def shutdown(ctx: dict) -> None:
    await ctx["saver"].__aexit__(None, None, None)
    await ctx["db"].close()


async def _before_failure(graph, cfg: dict) -> dict | None:
    """Newest checkpoint from before the run failed: history-based replay (C6)."""
    async for state in graph.aget_state_history(cfg):
        if state.next and state.values.get("status") != "needs_attention":
            return state.config
    return None


async def run_bid(ctx: dict, thread_id: str, trace_id: str | None = None,
                  replay: bool = False) -> str:
    lock = ctx["redis"].lock(f"lock:thread:{thread_id}", timeout=JOB_TIMEOUT)
    if not await lock.acquire(blocking=False):
        raise Retry(defer=30)  # another run of this thread is in progress
    try:
        return await _run(ctx, thread_id, trace_id, replay)
    finally:
        await lock.release()


async def _run(ctx: dict, thread_id: str, trace_id: str | None, replay: bool) -> str:
    pool, graph, redis = ctx["db"], ctx["graph"], ctx["redis"]
    row = await db.fetchone(pool, "SELECT t.job_id, t.pending_resume, u.account "
                                  "FROM bid_threads t JOIN users u ON u.id = t.user_id "
                                  "WHERE t.id = %s", thread_id)
    if not row:
        return "missing"
    cfg = {"configurable": {"thread_id": thread_id}}
    snap = await graph.aget_state(cfg)
    if row["pending_resume"] is not None and snap.interrupts:
        payload = Command(resume=row["pending_resume"])
    elif row["pending_resume"] is not None:
        payload = "already applied"  # applied before a crash; only the summary is stale
    elif replay:
        payload, cfg = None, await _before_failure(graph, cfg)
        if cfg is None:
            return "nothing to replay"
    elif not snap.values:
        payload = {"job_id": row["job_id"]}
        await db.fetchone(pool, "UPDATE bid_threads SET status = 'analyzing', "
                                "updated_at = now() WHERE id = %s RETURNING id", thread_id)
    elif snap.next and not snap.interrupts:
        payload = None  # the last run died mid-graph: continue from its checkpoint
    else:
        return "idle"  # finished, or waiting for a human

    if payload != "already applied":
        context = Context(toolbox=ctx["toolbox_for"](row["account"], trace_id))
        async for chunk in graph.astream(payload, cfg, context=context, stream_mode="updates"):
            for node, update in chunk.items():
                status = update.get("status") if isinstance(update, dict) else None
                await streaming.publish(redis, thread_id, {"event": "node", "node": node,
                                                           "status": status})
    values = (await graph.aget_state({"configurable": {"thread_id": thread_id}})).values
    await db.save_summary(pool, thread_id, values)
    status = values.get("status")
    await streaming.publish(redis, thread_id, {
        "event": "interrupt" if status == "awaiting_approval" else "done", "status": status})

    rules = load_config()["worker"]
    if status == "needs_attention" and any(t in (values.get("attention") or "")
                                           for t in TRANSIENT):
        attempt = await redis.incr(f"replays:{thread_id}")
        await redis.expire(f"replays:{thread_id}", 86400)
        if attempt <= rules["max_replays"]:
            await redis.enqueue_job(
                "run_bid", thread_id, trace_id=trace_id, replay=True,
                _defer_by=timedelta(minutes=rules["replay_delay_minutes"]),
                _job_id=f"replay:{thread_id}:{attempt}")
    return status or "unknown"


async def scout_tick(ctx: dict) -> int:
    """Runs every saved search that is due and re-queues orphaned threads; returns how
    many new jobs were queued."""
    pool, redis, queued = ctx["db"], ctx["redis"], 0
    limits = load_config()["scouting"]
    # Claim due searches atomically so two workers never run the same one.
    due = await db.fetch(pool, """
        WITH due AS (
            SELECT s.id, s.last_run_at FROM saved_searches s
            WHERE s.enabled AND (s.last_run_at IS NULL
                  OR s.last_run_at < now() - make_interval(mins => s.every_minutes))
            FOR UPDATE SKIP LOCKED)
        UPDATE saved_searches s SET last_run_at = now() FROM due, users u
        WHERE s.id = due.id AND u.id = s.user_id
        RETURNING s.id, s.user_id, s.query, s.skills, u.account, due.last_run_at AS since""")
    for search in due:
        toolbox = ctx["toolbox_for"](search["account"], None)
        limit = limits["per_run_limit"] if search["since"] else limits["first_run_limit"]
        args = {"query": search["query"], "skills": search["skills"], "limit": limit}
        if search["since"]:
            args["posted_after"] = search["since"].isoformat()
        try:
            page = await toolbox.call("scout", "marketplace", "search_jobs", args)
        except ToolCallError as e:  # try again next tick
            log.warning("search %s failed: %s", search["id"], e)
            await db.fetchone(pool, "UPDATE saved_searches SET last_run_at = %s WHERE id = %s "
                                    "RETURNING id", search["since"], search["id"])
            continue
        for job in page["jobs"]:
            if thread_id := await db.insert_thread(pool, search["user_id"], job):
                await redis.enqueue_job("run_bid", thread_id, _job_id=f"bid:{thread_id}")
                queued += 1

    orphans = await db.fetch(pool, "SELECT id FROM bid_threads WHERE status IN "
                                   "('queued', 'analyzing', 'processing') AND updated_at < "
                                   "now() - make_interval(mins => %s)",
                             load_config()["worker"]["orphan_after_minutes"])
    tick = int(time.time() // 300)  # Arq keeps finished job ids for an hour; vary per tick
    for orphan in orphans:  # a duplicate is harmless: run_bid reads state and locks
        await redis.enqueue_job("run_bid", str(orphan["id"]),
                                _job_id=f"sweep:{orphan['id']}:{tick}")
    return queued


class WorkerSettings:
    functions = (run_bid,)
    cron_jobs = (cron(scout_tick, minute=set(range(0, 60, 5))),)
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379"))
    max_jobs = load_config()["worker"]["max_jobs"]
    job_timeout = JOB_TIMEOUT
    max_tries = 3
    keep_result = 3600


async def _serve_without_signals() -> None:
    settings = {k: v for k, v in vars(WorkerSettings).items() if not k.startswith("_")}
    await Worker(**settings, handle_signals=False).async_run()  # built inside the running loop


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sys.platform == "win32":
        # No POSIX signals, and psycopg's async driver needs the selector loop.
        asyncio.run(_serve_without_signals(), loop_factory=asyncio.SelectorEventLoop)
    else:
        run_worker(WorkerSettings)  # graceful shutdown on SIGTERM
