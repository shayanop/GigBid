"""Postgres access shared by the API and the worker: one pool, plain SQL.

ponytail: the schema is applied with CREATE IF NOT EXISTS at startup; add migrations
(Alembic) once deployed data has to survive schema changes.
"""

import hashlib
import os
import re

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from agent.graphs.checkpoint import migration_lock

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text UNIQUE NOT NULL,
    password_hash text NOT NULL,
    account text NOT NULL,              -- marketplace account and portfolio folder
    settings jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS saved_searches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    query text NOT NULL DEFAULT '',
    skills text[] NOT NULL DEFAULT '{}',
    every_minutes int NOT NULL CHECK (every_minutes >= 15),  -- conservative polling only
    enabled boolean NOT NULL DEFAULT true,
    last_run_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS bid_threads (   -- one LangGraph thread per (user, job)
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    job_id text NOT NULL,
    content_hash text NOT NULL,         -- catches reposts of the same job under a new id
    title text NOT NULL,
    status text NOT NULL DEFAULT 'queued',
    summary jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, job_id),
    UNIQUE (user_id, content_hash)
);
-- Human decision waiting to be applied by the worker (outbox: survives a lost queue).
ALTER TABLE bid_threads ADD COLUMN IF NOT EXISTS pending_resume jsonb;
-- Pipeline stage, moved forward by submissions and client conversations.
ALTER TABLE bid_threads ADD COLUMN IF NOT EXISTS stage text NOT NULL DEFAULT 'drafted';
CREATE INDEX IF NOT EXISTS bid_threads_inbox ON bid_threads (user_id, status, updated_at DESC);
CREATE TABLE IF NOT EXISTS conversations (  -- one LangGraph thread per marketplace conversation
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users ON DELETE CASCADE,
    conversation_id text NOT NULL,
    job_id text NOT NULL,
    last_message_id text NOT NULL,      -- newest client message seen
    status text NOT NULL DEFAULT 'queued',
    summary jsonb NOT NULL DEFAULT '{}',
    pending_resume jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (user_id, conversation_id)
);
"""
STAGES = ["drafted", "submitted", "viewed", "replied", "interview", "hired", "lost"]
TABLES = {"bid_threads", "conversations"}  # the only tables the generic helpers touch


async def open_pool(url: str | None = None) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(url or os.environ["DATABASE_URL"], open=False,
                               kwargs={"row_factory": dict_row, "autocommit": True})
    await pool.open()
    async with migration_lock(url), pool.connection() as conn:
        await conn.execute(SCHEMA)
    return pool


async def fetch(pool: AsyncConnectionPool, sql: str, *args) -> list[dict]:
    async with pool.connection() as conn:
        return await (await conn.execute(sql, args)).fetchall()


async def fetchone(pool: AsyncConnectionPool, sql: str, *args) -> dict | None:
    async with pool.connection() as conn:
        return await (await conn.execute(sql, args)).fetchone()


def content_hash(job: dict) -> str:
    text = re.sub(r"\W+", " ", f"{job['title']} {job['description']}").lower().strip()
    return hashlib.sha256(text.encode()).hexdigest()


async def insert_thread(pool: AsyncConnectionPool, user_id, job: dict) -> str | None:
    """Creates the thread for a new job; None if this job or a repost of it exists."""
    row = await fetchone(
        pool, "INSERT INTO bid_threads (user_id, job_id, content_hash, title) "
              "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id",
        user_id, job["id"], content_hash(job), job["title"])
    return str(row["id"]) if row else None


def summarize_bid(values: dict) -> dict:
    """Inbox-sized view of a bid graph state."""
    out = {"attention": values.get("attention"),
           "tokens": (values.get("usage") or {}).get("tokens", 0)}
    if d := values.get("decision"):
        out |= {"decision": d.action, "reasons": d.reasons}
    if f := values.get("fit"):
        out["fit"] = f.score
    if r := values.get("risk"):
        out |= {"risk": r.score, "flags": r.flags, "injection": r.injection_detected}
    if p := values.get("price"):
        out |= {"price": p.amount, "budget_type": p.budget_type, "connects_cost": p.connects_cost}
    if s := values.get("submission"):
        out |= {"proposal_id": s.id, "submitted_connects": s.connects_cost}
    if values.get("rejection"):
        out["rejection"] = values["rejection"]
    return out


def summarize_conversation(values: dict) -> dict:
    """Messages-list view of a conversation graph state."""
    messages, job = values.get("messages") or [], values.get("job")
    out = {"attention": values.get("attention"), "title": job.title if job else None,
           "last_message": messages[-1].body[:200] if messages else None,
           "tokens": (values.get("usage") or {}).get("tokens", 0)}
    if i := values.get("intent"):
        out |= {"intent": i.intent, "intent_summary": i.summary}
    if values.get("rejection"):
        out["rejection"] = values["rejection"]
    return out


async def save_summary(pool: AsyncConnectionPool, table: str, thread_id: str,
                       values: dict) -> None:
    assert table in TABLES
    summary = summarize_bid(values) if table == "bid_threads" else summarize_conversation(values)
    await fetchone(pool, f"UPDATE {table} SET status = %s, summary = %s, pending_resume = NULL, "
                         "updated_at = now() WHERE id = %s RETURNING id",
                   values.get("status") or "queued", Jsonb(summary), thread_id)


async def advance_stage(pool: AsyncConnectionPool, user_id, job_id: str, stage: str) -> None:
    """Moves a bid's pipeline stage forward, never back."""
    await fetchone(pool, "UPDATE bid_threads SET stage = %s, updated_at = now() "
                         "WHERE user_id = %s AND job_id = %s AND "
                         "array_position(%s::text[], stage) < array_position(%s::text[], %s) "
                         "RETURNING id", stage, user_id, job_id, STAGES, STAGES, stage)


async def owned(pool: AsyncConnectionPool, table: str, user_id, thread_id) -> dict | None:
    assert table in TABLES
    return await fetchone(pool, f"SELECT * FROM {table} WHERE id = %s AND user_id = %s",
                          thread_id, user_id)


async def owned_thread(pool: AsyncConnectionPool, user_id, thread_id) -> dict | None:
    return await owned(pool, "bid_threads", user_id, thread_id)


async def claim_decision(pool: AsyncConnectionPool, table: str, user_id, thread_id,
                         decision: dict) -> bool:
    """Atomically records a human decision on a thread waiting for one. A double click
    or a second tab cannot apply it twice, and the decision is stored before it is
    queued, so a lost queue entry cannot lose it."""
    assert table in TABLES
    return bool(await fetchone(
        pool, f"UPDATE {table} SET status = 'processing', pending_resume = %s, "
              "updated_at = now() WHERE id = %s AND user_id = %s AND "
              "status = 'awaiting_approval' RETURNING id",
        Jsonb(decision), thread_id, user_id))
