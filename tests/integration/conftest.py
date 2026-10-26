"""Shared integration fixtures: in-process GigSim and MCP servers, a scripted fake LLM,
and (when TEST_DATABASE_URL / TEST_REDIS_URL are set) real Postgres and Redis."""

import asyncio
import os
import re
import sys
from types import SimpleNamespace

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent.config import load_config
from agent.graphs.checkpoint import serde
from agent.handoffs import (
    ClaimCheck,
    ClaimReport,
    ComplianceVerdict,
    Critique,
    FitReport,
    JobSpec,
    ProposalDraft,
    RequirementMatch,
    RiskReport,
)
from agent.mcp_client import Toolbox
from agent.nodes import common
from gigsim.app import create_app
from mcp_servers.marketplace import server as marketplace
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter
from mcp_servers.portfolio import server as portfolio

if sys.platform == "win32":  # psycopg's async driver cannot use the Proactor event loop
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

FAKE_ID = "fr_ml-p99#0"  # not in the portfolio; the verifier must reject claims citing it
FILLER = "I would start with a short call to confirm scope, data access and milestones. " * 6


class FakeLLM:
    """Stands in for common.ask; returns schema objects shaped like real model output."""

    def __init__(self, critic_rejections=0, fit=0.9, compliance="pass"):
        self.critic_rejections, self.fit, self.verdict = critic_rejections, fit, compliance
        self.calls: list[str] = []

    async def __call__(self, node, schema, user):
        self.calls.append(node)
        return getattr(self, node)(user)

    def analyst(self, user):
        return JobSpec(deliverables=["working system"], skills=["Python"],
                       requirements=["Build the pipeline"], budget="stated", timeline="stated")

    def risk(self, user):
        return RiskReport(score=0.05, flags=[], injection_detected=False, summary="Looks fine.")

    def matcher(self, user):
        first = re.search(r"^\[([^\]]+)\]", user, re.MULTILINE).group(1)
        return FitReport(score=self.fit, reasons=["covers the stack"], matches=[
            RequirementMatch(requirement="Build the pipeline", strength="strong",
                             evidence_ids=[first, "made-up#9"])])

    def writer(self, user):
        evidence_id = re.search(r"^\[([^\]]+)\]", user.split("Evidence:")[1], re.MULTILINE).group(1)
        return ProposalDraft(cover_letter=(
            f"Your team needs answers grounded in its own documents. I built a retrieval "
            f"pipeline for a similar client [{evidence_id}]. I have 15 years of Rust "
            f"experience [{FAKE_ID}]. {FILLER}"))

    def verifier(self, user):
        letter = user.split("Proposal:\n")[1]
        sentences = re.split(r"(?<=[.!?])\s+", letter)
        built = next(s for s in sentences if "retrieval pipeline" in s)
        rust = next((s for s in sentences if "Rust" in s), None)
        claims = [ClaimCheck(sentence=built, claim="built a retrieval pipeline",
                             evidence_ids=[re.search(r"\[([^\]]+)\]", built).group(1)],
                             label="supported")]
        if rust:  # labelled supported by the "model", but cites an id that does not exist
            claims.append(ClaimCheck(sentence=rust, claim="15 years of Rust",
                                     evidence_ids=[FAKE_ID], label="supported"))
        return ClaimReport(claims=claims)

    def critic(self, user):
        reject = self.critic_rejections > 0
        self.critic_rejections -= 1
        return Critique(approve=not reject, issues=["too generic"] * reject,
                        instructions="Be more specific." * reject)

    def compliance(self, user):
        return ComplianceVerdict(status=self.verdict, violations=[],
                                 reason="ok" if self.verdict == "pass" else "fabrication")


@pytest.fixture
def harness(monkeypatch, offline_rag, tmp_path):
    app = create_app()
    for var, value in {"MARKETPLACE_LOCAL_USER": "fr_ml", "PORTFOLIO_LOCAL_USER": "fr_ml",
                       "MARKETPLACE_AUDIT_LOG": str(tmp_path / "audit.jsonl"),
                       "MARKETPLACE_RATE_PER_MIN": "1000"}.items():
        monkeypatch.setenv(var, value)
    marketplace._calls.clear()
    monkeypatch.setattr(marketplace, "adapter_for", lambda user: GigSimAdapter(
        "http://gigsim", user, transport=httpx.ASGITransport(app=app), backoff=0))
    monkeypatch.setitem(load_config()["budgets"], "retry_initial_seconds", 0.01)
    fake = FakeLLM()
    monkeypatch.setattr(common, "ask", fake)
    toolbox = Toolbox({"marketplace": marketplace.mcp, "portfolio": portfolio.mcp}, backoff=0)

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
