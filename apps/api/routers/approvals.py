"""Human approval (R4, C5): the only way a proposal leaves GigBid. Never automatic."""

from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from psycopg.types.json import Jsonb

from agent.handoffs import Approval
from apps.api import db
from apps.api.auth import User
from apps.api.routers.jobs import enqueue_run, to_summary
from apps.api.schemas import Accepted, ApprovalRequest, JobSummary

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[JobSummary])
async def pending(user: User, request: Request):
    rows = await db.fetch(request.app.state.db,
                          "SELECT * FROM bid_threads WHERE user_id = %s AND "
                          "status = 'awaiting_approval' ORDER BY updated_at", user["id"])
    return [to_summary(r) for r in rows]


@router.get("/{thread_id}", response_model=ApprovalRequest)
async def review(thread_id: UUID, user: User, request: Request):
    """Draft, evidence per claim, risk, price rationale and dry-run preview. Survives
    browser refreshes and API restarts: it is read from the graph checkpoint."""
    row = await db.owned_thread(request.app.state.db, user["id"], thread_id)
    snap = await request.app.state.graph.aget_state({"configurable": {"thread_id": str(thread_id)}})
    if not row or not snap.interrupts:
        raise HTTPException(404, "nothing awaiting approval")
    return {"thread_id": thread_id, "title": row["title"], "request": snap.interrupts[0].value}


@router.post("/{thread_id}", response_model=Accepted, status_code=202)
async def decide(thread_id: UUID, body: Approval, user: User, request: Request):
    pool = request.app.state.db
    row = await db.owned_thread(pool, user["id"], thread_id)
    if not row or row["status"] != "awaiting_approval":
        raise HTTPException(409, "not awaiting approval")
    budget = user["settings"].get("weekly_connects_budget")
    if body.action == "approve" and budget is not None:
        spent = await db.fetchone(
            pool, "SELECT coalesce(sum((summary->>'submitted_connects')::int), 0) AS n "
                  "FROM bid_threads WHERE user_id = %s AND status = 'submitted' "
                  "AND updated_at > now() - interval '7 days'", user["id"])
        cost = row["summary"].get("connects_cost") or 0
        if spent["n"] + cost > budget:
            raise HTTPException(409, f"weekly Connects budget: {spent['n']} of {budget} used, "
                                     f"this bid needs {cost}")
    # Atomic claim: a double click or a second tab cannot resume the graph twice. The
    # decision is stored before queueing, so a lost queue entry cannot lose it.
    claimed = await db.fetchone(pool, "UPDATE bid_threads SET status = 'processing', "
                                      "pending_resume = %s, updated_at = now() WHERE id = %s "
                                      "AND user_id = %s AND status = 'awaiting_approval' "
                                      "RETURNING id",
                                Jsonb(body.model_dump()), thread_id, user["id"])
    if not claimed:
        raise HTTPException(409, "not awaiting approval")
    await enqueue_run(request, str(thread_id), _job_id=f"resume:{thread_id}:{uuid4().hex}")
    return {"thread_id": thread_id, "status": "processing"}
