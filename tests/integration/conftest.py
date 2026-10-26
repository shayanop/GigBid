"""Shared integration fixtures: in-process GigSim and MCP servers, a scripted fake LLM,
and (when TEST_DATABASE_URL / TEST_REDIS_URL are set) real Postgres and Redis."""

import asyncio
import os
import sys
from types import SimpleNamespace

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent.config import load_config
from agent.fake_llm import FILLER, FakeLLM
from agent.graphs.checkpoint import serde
from agent.mcp_client import Toolbox
from agent.nodes import common
from gigsim.app import create_app
from mcp_servers.marketplace import server as marketplace
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from mcp_servers.portfolio import server as portfolio
from mcp_servers.workspace import server as workspace

if sys.platform == "win32":  # psycopg's async driver cannot use the Proactor event loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

@pytest.fixture
def harness(monkeypatch, offline_rag, tmp_path):
    app = create_app()
    for var, value in {"MARKETPLACE_LOCAL_USER": "fr_ml", "PORTFOLIO_LOCAL_USER": "fr_ml",
                       "MARKETPLACE_AUDIT_LOG": str(tmp_path / "audit.jsonl"),
                       "MARKETPLACE_RATE_PER_MIN": "1000", "WORKSPACE_LOCAL_USER": "fr_ml",
                       "WORKSPACE_DIR": str(tmp_path / "workspace")}.items():
        monkeypatch.setenv(var, value)
    marketplace._calls.clear()
    monkeypatch.setattr(marketplace, "adapter_for", lambda user: GigSimAdapter(
        "http://gigsim", user, transport=httpx.ASGITransport(app=app), backoff=0))
    monkeypatch.setitem(load_config()["budgets"], "retry_initial_seconds", 0.01)
    fake = FakeLLM()
    monkeypatch.setattr(common, "ask", fake)
    toolbox = Toolbox({"marketplace": marketplace.mcp, "portfolio": portfolio.mcp,
                       "workspace": workspace.mcp}, backoff=0)

    def job(scam: bool) -> str:
        return next(j["id"] for j in app.state.data["jobs"].values()
                    if j["_truth"]["category"] == "ml" and j["_truth"]["scam"] == scam
                    and not j["_truth"]["injection"] and not j["_truth"]["duplicate_of"])

    return SimpleNamespace(app=app, fake=fake, filler=FILLER, saver=InMemorySaver(serde=serde()), job=job,
                           ctx=common.Context(toolbox=toolbox),
                           cfg={"configurable": {"thread_id": "thread-1"}},
                           balance=lambda: app.state.data["freelancers"]["fr_ml"]["connects"])


@pytest.fixture
async def infra(monkeypatch):
    """Real Postgres and Redis, emptied for each test."""
    db_url, redis_url = os.getenv("TEST_DATABASE_URL"), os.getenv("TEST_REDIS_URL")
    if not (db_url and redis_url):
        pytest.skip("TEST_DATABASE_URL / TEST_REDIS_URL not set")
    for var, value in {"DATABASE_URL": db_url, "REDIS_URL": redis_url,
                       "SESSION_SECRET": "test-session-secret-0123456789",
                       "MCP_SIGNING_SECRET": "test-signing-secret"}.items():
        monkeypatch.setenv(var, value)
    import psycopg
    from redis.asyncio import Redis

    from apps.api.db import SCHEMA
    async with await psycopg.AsyncConnection.connect(db_url, autocommit=True) as conn:
        await conn.execute(SCHEMA)
        await conn.execute("TRUNCATE users, saved_searches, bid_threads CASCADE")
    async with Redis.from_url(redis_url) as redis:
        await redis.flushdb()
