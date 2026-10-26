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
CREATE INDEX IF NOT EXISTS bid_threads_inbox ON bid_threads (user_id, status, updated_at DESC);
"""


async def open_pool(url: str | None = None) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(url or os.environ["DATABASE_URL"], open=False,
                               kwargs={"row_factory": dict_row, "autocommit": True})
    await pool.open()
    async with pool.connection() as conn:
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


def summarize(values: dict) -> dict:
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


async def save_summary(pool: AsyncConnectionPool, thread_id: str, values: dict) -> None:
    await fetchone(pool, "UPDATE bid_threads SET status = %s, summary = %s, "
                         "pending_resume = NULL, updated_at = now() WHERE id = %s RETURNING id",
                   values.get("status") or "queued", Jsonb(summarize(values)), thread_id)


async def owned_thread(pool: AsyncConnectionPool, user_id, thread_id) -> dict | None:
    return await fetchone(pool, "SELECT * FROM bid_threads WHERE id = %s AND user_id = %s",
                          thread_id, user_id)
