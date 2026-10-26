"""Client conversations: drafted replies wait here for approval. Nothing is sent without it."""

import time
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request

from agent.handoffs import Approval
from apps.api import db
from apps.api.auth import User
from apps.api.schemas import Accepted, ConversationDetail, ConversationSummary

router = APIRouter(prefix="/messages", tags=["messages"])
SUMMARY_FIELDS = ("title", "last_message", "intent", "intent_summary", "attention")


def to_summary(row: dict) -> dict:
    s = row["summary"]
    return {"id": row["id"], "conversation_id": row["conversation_id"], "job_id": row["job_id"],
            "status": row["status"], "updated_at": row["updated_at"],
            **{k: s[k] for k in SUMMARY_FIELDS if s.get(k) is not None}}


@router.get("", response_model=list[ConversationSummary])
async def conversations(user: User, request: Request):
    """Conversations waiting for you first, then the most recent."""
    rows = await db.fetch(request.app.state.db,
                          "SELECT * FROM conversations WHERE user_id = %s ORDER BY "
                          "status = 'awaiting_approval' DESC, updated_at DESC", user["id"])
    return [to_summary(r) for r in rows]


@router.post("/refresh", response_model=dict, status_code=202)
async def refresh(user: User, request: Request):
    """Check the marketplace for new client messages now instead of at the next tick."""
    minute = int(time.time() // 60)  # at most one check per user per minute
    await request.app.state.queue.enqueue_job("check_inbox", str(user["id"]),
                                              trace_id=request.state.trace_id,
                                              _job_id=f"inbox:{user['id']}:{minute}")
    return {"status": "checking"}


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def conversation(conversation_id: UUID, user: User, request: Request):
    row = await db.owned(request.app.state.db, "conversations", user["id"], conversation_id)
    if not row:
        raise HTTPException(404, "conversation not found")
    snap = await request.app.state.conversation_graph.aget_state(
        {"configurable": {"thread_id": str(conversation_id)}})
    v = snap.values
    return {**to_summary(row), "messages": v.get("messages") or [],
            "intent_detail": v.get("intent"), "slots": v.get("slots") or [],
            "reply": v["reply"].body if v.get("reply") else None,
            "approval_request": snap.interrupts[0].value if snap.interrupts else None}


@router.post("/{conversation_id}", response_model=Accepted, status_code=202)
async def decide(conversation_id: UUID, body: Approval, user: User, request: Request):
    if not await db.claim_decision(request.app.state.db, "conversations", user["id"],
                                   conversation_id, body.model_dump()):
        raise HTTPException(409, "no reply is waiting for approval")
    await request.app.state.queue.enqueue_job(
        "run_conversation", str(conversation_id), trace_id=request.state.trace_id,
        _job_id=f"resume:{conversation_id}:{uuid4().hex}")
    return {"thread_id": conversation_id, "status": "processing"}
