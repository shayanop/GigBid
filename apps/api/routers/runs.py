"""Agent run viewer: node-by-node trace and live progress (SSE)."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.sse import EventSourceResponse

from apps.api import db, streaming
from apps.api.auth import User
from apps.api.schemas import TraceOut

router = APIRouter(prefix="/runs", tags=["runs"])


async def _state(request: Request, user: dict, thread_id: UUID):
    row = await db.owned_thread(request.app.state.db, user["id"], thread_id)
    if not row:
        raise HTTPException(404, "run not found")
    snap = await request.app.state.graph.aget_state({"configurable": {"thread_id": str(thread_id)}})
    return row, snap.values


@router.get("/{thread_id}", response_model=TraceOut)
async def trace(thread_id: UUID, user: User, request: Request):
    row, values = await _state(request, user, thread_id)
    return {"status": row["status"], "usage": values.get("usage") or {},
            "trace": values.get("trace") or []}


@router.get("/{thread_id}/events", response_class=EventSourceResponse)
async def events(thread_id: UUID, user: User, request: Request):
    await _state(request, user, thread_id)  # ownership check before streaming

    async def snapshot():
        row, values = await _state(request, user, thread_id)
        return {"status": row["status"], "nodes": [t["node"] for t in values.get("trace", [])]}

    async for event in streaming.relay(request, str(thread_id), snapshot):
        yield event
