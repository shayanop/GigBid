"""Marketplace MCP server (A2): read and write tools over the configured MarketplacePort.

Every call is bearer-authenticated, rate limited per user and appended to an
audit log with a trace ID. Writes take an idempotency key and support dry_run
previews for the approval UI.

Run: python -m mcp_servers.marketplace.server  (Streamable HTTP, /mcp)
"""

import json
import os
import time
import uuid
from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from agent.config import load_config
from agent.marketplace_port import (
    Client,
    Job,
    JobPage,
    MarketplaceError,
    MarketplacePort,
    MarketplaceUnavailable,
    Message,
    Proposal,
    ProposalIn,
    Thread,
)
from agent.redact import redact
from mcp_servers.auth import bearer_auth, current_user
from mcp_servers.marketplace.adapters.gigsim import GigSimAdapter

READ = ToolAnnotations(read_only_hint=True, open_world_hint=True)
DRAFT = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=True,
                        open_world_hint=True)
SPEND = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=True,
                        open_world_hint=True)

Id = Annotated[str, Field(pattern=r"^[\w-]{1,64}$")]
IdemKey = Annotated[str, Field(min_length=8, max_length=128, description=(
    "Unique key for this intended write. Reuse the same key when retrying it."))]
Text = Annotated[str, Field(min_length=1, max_length=5000)]


class ConnectsBalance(BaseModel):
    balance: int


class DraftResult(BaseModel):
    dry_run: bool
    payload: ProposalIn
    connects_cost: int = Field(description="Connects charged when the draft is submitted")
    connects_balance: int
    proposal: Proposal | None = None


class SubmitResult(BaseModel):
    dry_run: bool
    connects_cost: int
    connects_balance_after: int
    proposal: Proposal


class MessageResult(BaseModel):
    dry_run: bool
    thread_id: str
    body: str
    message: Message | None = None


URL = os.getenv("MARKETPLACE_MCP_URL", "http://localhost:8200/mcp")
mcp = MCPServer(
    "gigbid-marketplace",
    instructions="Marketplace jobs, clients, Connects, proposals and messages. Writes need "
                 "explicit human approval upstream; use dry_run to preview.",
    **bearer_auth(URL),
)

_calls: dict[str, deque] = defaultdict(deque)


def adapter_for(user: str) -> MarketplacePort:
    name = load_config()["marketplace"]["adapter"]
    if name == "gigsim":
        # ponytail: GigSim token is the user id; per-user credentials arrive with the API.
        return GigSimAdapter(os.getenv("GIGSIM_URL", "http://localhost:8100"), token=user)
    raise ToolError(f"marketplace adapter {name!r} is not available yet")


def _audit(user: str, tool: str, args: dict, result, trace_id: str) -> None:
    # ponytail: append-only JSONL file; move to a Postgres table without UPDATE/DELETE grants.
    path = Path(os.getenv("MARKETPLACE_AUDIT_LOG", "data/processed/audit/marketplace.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"ts": datetime.now(UTC).isoformat(), "trace_id": trace_id, "user": user,
              "tool": tool, "args": redact(args), "result": redact(result)}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


async def _run(ctx: Context, tool: str, args: dict, call):
    user = current_user("MARKETPLACE")
    trace_id = (ctx.headers or {}).get("x-trace-id") or uuid.uuid4().hex
    window, now = _calls[user], time.monotonic()
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= int(os.getenv("MARKETPLACE_RATE_PER_MIN", "60")):
        _audit(user, tool, args, {"error": "rate limited"}, trace_id)
        raise ToolError("rate limited: too many marketplace calls this minute, retry later")
    window.append(now)
    try:
        result = await call(adapter_for(user))
    except MarketplaceUnavailable as e:
        _audit(user, tool, args, {"error": f"unavailable: {e}"}, trace_id)
        raise ToolError(f"marketplace unavailable: {e}") from e
    except MarketplaceError as e:
        _audit(user, tool, args, {"error": str(e)}, trace_id)
        raise ToolError(str(e)) from e
    dumped = ([r.model_dump(mode="json") for r in result] if isinstance(result, list)
              else result.model_dump(mode="json"))
    _audit(user, tool, args, dumped, trace_id)
    return result


@mcp.tool(annotations=READ)
async def search_jobs(
    ctx: Context,
    query: Annotated[str, Field(max_length=200, description="Keywords, all must match")] = "",
    skills: Annotated[list[str], Field(max_length=10, description="Match any skill")] = [],
    posted_after: datetime | None = None,
    limit: Annotated[int, Field(ge=1, le=50)] = 20,
    offset: Annotated[int, Field(ge=0, le=10_000)] = 0,
) -> JobPage:
    """Search open jobs by keywords and skills, newest first."""
    args = {"query": query, "skills": skills, "posted_after": posted_after, "limit": limit, "offset": offset}
    return await _run(ctx, "search_jobs", args, lambda m: m.search_jobs(**args))


@mcp.tool(annotations=READ)
async def get_job(ctx: Context, job_id: Id) -> Job:
    """Get one job posting with its full description and screening questions."""
    return await _run(ctx, "get_job", {"job_id": job_id}, lambda m: m.get_job(job_id))


@mcp.tool(annotations=READ)
async def get_client_history(ctx: Context, client_id: Id) -> Client:
    """Get a client's hiring history: spend, hire rate, rating, reviews, payment status."""
    return await _run(ctx, "get_client_history", {"client_id": client_id},
                      lambda m: m.get_client(client_id))


@mcp.tool(annotations=READ)
async def get_connects_balance(ctx: Context) -> ConnectsBalance:
    """Get the freelancer's current Connects balance."""
    async def call(m: MarketplacePort):
        return ConnectsBalance(balance=await m.get_connects())
    return await _run(ctx, "get_connects_balance", {}, call)


@mcp.tool(annotations=READ)
async def list_messages(ctx: Context) -> list[Thread]:
    """List the freelancer's client conversations with all messages."""
    return await _run(ctx, "list_messages", {}, lambda m: m.list_threads())


@mcp.tool(annotations=DRAFT)
async def create_proposal_draft(
    ctx: Context, job_id: Id, cover_letter: Text,
    bid_amount: Annotated[float, Field(gt=0, le=1_000_000)], idempotency_key: IdemKey,
    screening_answers: Annotated[list[str], Field(max_length=10)] = [], dry_run: bool = False,
) -> DraftResult:
    """Save a proposal as a marketplace draft. Spends no Connects. With dry_run, only
    preview the payload and the Connects that submitting it would cost."""
    draft = ProposalIn(job_id=job_id, cover_letter=cover_letter, bid_amount=bid_amount,
                       screening_answers=screening_answers)

    async def call(m: MarketplacePort):
        job, balance = await m.get_job(job_id), await m.get_connects()
        proposal = None if dry_run else await m.create_proposal_draft(draft, idempotency_key)
        return DraftResult(dry_run=dry_run, payload=draft, connects_cost=job.connects_cost,
                           connects_balance=balance, proposal=proposal)
    args = draft.model_dump() | {"idempotency_key": idempotency_key, "dry_run": dry_run}
    return await _run(ctx, "create_proposal_draft", args, call)


@mcp.tool(annotations=SPEND)
async def submit_proposal(ctx: Context, proposal_id: Id, idempotency_key: IdemKey,
                          dry_run: bool = False) -> SubmitResult:
    """Submit an approved proposal draft. Spends Connects and cannot be undone.
    With dry_run, only preview the cost and remaining balance."""
    async def call(m: MarketplacePort):
        proposal, balance = await m.get_proposal(proposal_id), await m.get_connects()
        if not dry_run:
            proposal = await m.submit_proposal(proposal_id, idempotency_key)
            balance = await m.get_connects()
        else:
            balance -= proposal.connects_cost
        return SubmitResult(dry_run=dry_run, connects_cost=proposal.connects_cost,
                            connects_balance_after=balance, proposal=proposal)
    args = {"proposal_id": proposal_id, "idempotency_key": idempotency_key, "dry_run": dry_run}
    return await _run(ctx, "submit_proposal", args, call)


@mcp.tool(annotations=DRAFT)
async def send_message(ctx: Context, thread_id: Id, body: Text, idempotency_key: IdemKey,
                       dry_run: bool = False) -> MessageResult:
    """Send an approved reply in a client conversation. With dry_run, only preview it."""
    async def call(m: MarketplacePort):
        msg = None if dry_run else await m.send_message(thread_id, body, idempotency_key)
        return MessageResult(dry_run=dry_run, thread_id=thread_id, body=body, message=msg)
    args = {"thread_id": thread_id, "body": body, "idempotency_key": idempotency_key,
            "dry_run": dry_run}
    return await _run(ctx, "send_message", args, call)


if __name__ == "__main__":
    mcp.run("streamable-http", host=os.getenv("HOST", "127.0.0.1"),
            port=int(os.getenv("PORT", "8200")))
