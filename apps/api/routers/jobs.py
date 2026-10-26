from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from agent.mcp_client import ToolCallError, ToolUnavailable
from apps.api import db
from apps.api.auth import User
from apps.api.schemas import AnalyzeIn, EvidenceOut, JobDetail, JobSummary

router = APIRouter(prefix="/jobs", tags=["jobs"])
SUMMARY_FIELDS = ("decision", "fit", "risk", "flags", "price", "connects_cost", "attention")


def to_summary(row: dict) -> dict:
    s = row["summary"]
    return {"thread_id": row["id"], "job_id": row["job_id"], "title": row["title"],
            "status": row["status"], "updated_at": row["updated_at"],
            **{k: s[k] for k in SUMMARY_FIELDS if s.get(k) is not None}}


async def enqueue_run(request: Request, thread_id: str, **kwargs) -> None:
    await request.app.state.queue.enqueue_job(
        "run_bid", thread_id, trace_id=request.state.trace_id, **kwargs)


@router.get("", response_model=list[JobSummary])
async def inbox(user: User, request: Request, status: str | None = None,
                limit: int = Query(50, ge=1, le=200)):
    """Jobs ranked by fit, best first; optionally only one status."""
    rows = await db.fetch(
        request.app.state.db,
        "SELECT * FROM bid_threads WHERE user_id = %s AND (%s::text IS NULL OR status = %s) "
        "ORDER BY (summary->>'fit')::float DESC NULLS LAST, updated_at DESC LIMIT %s",
        user["id"], status, status, limit)
    return [to_summary(r) for r in rows]


@router.post("", response_model=JobSummary, status_code=202)
async def analyze(body: AnalyzeIn, user: User, request: Request):
    """Queue one marketplace job for analysis (saved searches do this on a schedule)."""
    toolbox = request.app.state.toolbox_for(user["account"], request.state.trace_id)
    try:
        job = await toolbox.call("scout", "marketplace", "get_job", {"job_id": body.job_id})
    except ToolUnavailable:
        raise HTTPException(503, "marketplace unavailable, try again shortly") from None
    except ToolCallError as e:
        raise HTTPException(404, str(e)) from None
    thread_id = await db.insert_thread(request.app.state.db, user["id"], job)
    if not thread_id:
        raise HTTPException(409, "this job (or a repost of it) is already in your inbox")
    await enqueue_run(request, thread_id, _job_id=f"bid:{thread_id}")
    return to_summary(await db.owned_thread(request.app.state.db, user["id"], thread_id))


@router.get("/{thread_id}", response_model=JobDetail)
async def detail(thread_id: UUID, user: User, request: Request):
    row = await db.owned_thread(request.app.state.db, user["id"], thread_id)
    if not row:
        raise HTTPException(404, "job not found")
    snap = await request.app.state.graph.aget_state({"configurable": {"thread_id": str(thread_id)}})
    v = snap.values
    return {**to_summary(row), "spec": v.get("spec"), "risk_report": v.get("risk"),
            "fit_report": v.get("fit"), "decision_detail": v.get("decision"),
            "price_quote": v.get("price"), "draft": v.get("draft"), "claims": v.get("claims"),
            "critique": v.get("critique"), "compliance": v.get("compliance"),
            "evidence": [EvidenceOut.model_validate(e.model_dump()) for e in v.get("evidence", [])]}
