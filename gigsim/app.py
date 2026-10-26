"""GigSim: an in-memory marketplace REST API for safe development and evaluation.

Simulates per-freelancer auth, Connects, proposal drafts and submission,
message threads, rate limits (429 + Retry-After) and random 5xx outages.
Writes require an Idempotency-Key header; replays return the first response.

Run: uvicorn gigsim.app:create_app --factory --port 8100
"""

import hashlib
import json
import os
import random
import re
import time
from collections import defaultdict, deque
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from gigsim import seed


class ProposalIn(BaseModel):
    job_id: str
    cover_letter: str = Field(min_length=1, max_length=5000)
    screening_answers: list[str] = []
    bid_amount: float = Field(gt=0)


class MessageIn(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


def public(record: dict) -> dict:
    return {k: v for k, v in record.items() if not k.startswith("_")}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _get(table: dict, key: str) -> dict:
    if key not in table:
        raise HTTPException(404, f"{key} not found")
    return table[key]


GENERIC_OPENING = re.compile(r"dear sir|i am an expert|best fit for|i can do this job"
                             r"|check my profile", re.IGNORECASE)
CLIENT_LINES = {
    "interview": "Your proposal stood out. Could we do a 30-minute call this week to talk it "
                 "through?",
    "question": "Thanks for applying. How would you structure the first milestone, and what "
                "do you need from us to start?",
    "scam": "Thanks for applying. Let's continue on WhatsApp, my number is +1 555 0100. "
            "I'll pay you directly so we both save the fees.",
}


def simulate_client(state: dict, me: dict, proposal: dict) -> None:
    """The client's reaction to a submitted proposal, decided from their hidden
    preferences: budget ceiling and dislike of generic openings. Deterministic per job
    and freelancer. ponytail: rule-based; an LLM client comes with the outcome evals."""
    job = state["jobs"][proposal["job_id"]]
    client = state["clients"][job["client_id"]]
    prefs = client["_prefs"]
    if prefs is None:
        intent = "scam"
    else:
        rng = random.Random(f"{job['id']}:{me['id']}")
        score = 0.45 + rng.uniform(-0.15, 0.15)
        ceiling = (job["budget_max"] or proposal["bid_amount"]) * prefs["budget_ceiling_pct"]
        score += 0.25 if proposal["bid_amount"] <= ceiling else -0.25
        if prefs["dislikes_generic_opening"] and GENERIC_OPENING.search(proposal["cover_letter"][:200]):
            score -= 0.3
        if score < 0.4:
            return  # ignored, as most proposals are
        intent = "interview" if score >= 0.6 else "question"
    tid = f"th_{len(state['threads']) + 1:04d}"
    state["threads"][tid] = {
        "id": tid, "freelancer_id": me["id"], "job_id": job["id"], "client_id": client["id"],
        "messages": [{"id": f"{tid}_m1", "sender": "client", "body": CLIENT_LINES[intent],
                      "sent_at": _now()}],
        "_intent": intent,
    }


def create_app(n_jobs: int = 1500, rate_per_min: int | None = None,
               error_rate: float | None = None) -> FastAPI:
    # ponytail: in-memory state and idempotency keys reset on restart; fine for a simulator.
    state = seed.build(n_jobs)
    rate = rate_per_min or int(os.getenv("GIGSIM_RATE_PER_MIN", "120"))
    errors = error_rate if error_rate is not None else float(os.getenv("GIGSIM_ERROR_RATE", "0"))
    hits: dict[str, deque] = defaultdict(deque)
    replies: dict[tuple[str, str], tuple[str, dict]] = {}
    chaos = random.Random()
    app = FastAPI(title="GigSim")
    app.state.data = state

    @app.middleware("http")
    async def limits_and_outages(request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        window = hits[request.headers.get("authorization", "")]
        now = time.monotonic()
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= rate:
            retry = int(60 - (now - window[0])) + 1
            return JSONResponse({"detail": "rate limited"}, 429, {"Retry-After": str(retry)})
        window.append(now)
        if chaos.random() < errors:
            return JSONResponse({"detail": "simulated outage"}, 503)
        return await call_next(request)

    def freelancer(authorization: Annotated[str, Header()] = "") -> dict:
        fid = authorization.removeprefix("Bearer ").strip()
        if fid not in state["freelancers"]:
            raise HTTPException(401, "invalid token")
        return state["freelancers"][fid]

    Me = Annotated[dict, Depends(freelancer)]
    IdemKey = Annotated[str, Header()]

    def once(me: dict, key: str, request: dict, write) -> dict:
        if not key:
            raise HTTPException(400, "Idempotency-Key header required")
        fingerprint = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        slot = (me["id"], key)
        if slot in replies:
            if replies[slot][0] != fingerprint:
                raise HTTPException(422, "Idempotency-Key reused for a different request")
            return replies[slot][1]
        result = dict(write())
        replies[slot] = (fingerprint, result)
        return result

    def my_proposal(me: dict, proposal_id: str) -> dict:
        p = _get(state["proposals"], proposal_id)
        if p["freelancer_id"] != me["id"]:
            raise HTTPException(404, f"{proposal_id} not found")
        return p

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.get("/jobs")
    def search_jobs(me: Me, q: str = "", skills: str = "", posted_after: datetime | None = None,
                    limit: int = Query(20, ge=1, le=50), offset: int = Query(0, ge=0)):
        words = q.lower().split()
        wanted = {s.strip().lower() for s in skills.split(",") if s.strip()}
        if posted_after and posted_after.tzinfo is None:
            posted_after = posted_after.replace(tzinfo=UTC)
        found = [
            j for j in sorted(state["jobs"].values(), key=lambda j: j["posted_at"], reverse=True)
            if all(w in f"{j['title']} {j['description']}".lower() for w in words)
            and (not wanted or wanted & {s.lower() for s in j["skills"]})
            and (not posted_after or datetime.fromisoformat(j["posted_at"]) > posted_after)
        ]
        return {"total": len(found), "jobs": [public(j) for j in found[offset:offset + limit]]}

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str, me: Me):
        return public(_get(state["jobs"], job_id))

    @app.get("/clients/{client_id}")
    def get_client(client_id: str, me: Me):
        return public(_get(state["clients"], client_id))

    @app.get("/me/connects")
    def connects(me: Me):
        return {"balance": me["connects"]}

    @app.get("/threads")
    def threads(me: Me):
        return [public(t) for t in state["threads"].values() if t["freelancer_id"] == me["id"]]

    @app.get("/proposals/{proposal_id}")
    def get_proposal(proposal_id: str, me: Me):
        return my_proposal(me, proposal_id)

    @app.post("/proposals", status_code=201)
    def create_proposal(body: ProposalIn, me: Me, idempotency_key: IdemKey = ""):
        def write():
            job = _get(state["jobs"], body.job_id)
            pid = f"pr_{len(state['proposals']) + 1:05d}"
            state["proposals"][pid] = {
                "id": pid, "freelancer_id": me["id"], **body.model_dump(), "status": "draft",
                "connects_cost": job["connects_cost"], "created_at": _now(), "submitted_at": None,
            }
            return state["proposals"][pid]
        return once(me, idempotency_key, {"op": "create", **body.model_dump()}, write)

    @app.post("/proposals/{proposal_id}/submit")
    def submit_proposal(proposal_id: str, me: Me, idempotency_key: IdemKey = ""):
        def write():
            p = my_proposal(me, proposal_id)
            if p["status"] != "draft":
                raise HTTPException(409, "proposal already submitted")
            if me["connects"] < p["connects_cost"]:
                raise HTTPException(402, "insufficient connects")
            me["connects"] -= p["connects_cost"]
            p.update(status="submitted", submitted_at=_now())
            simulate_client(state, me, p)
            return p
        return once(me, idempotency_key, {"op": "submit", "id": proposal_id}, write)

    @app.post("/threads/{thread_id}/messages", status_code=201)
    def send_message(thread_id: str, body: MessageIn, me: Me, idempotency_key: IdemKey = ""):
        def write():
            thread = _get(state["threads"], thread_id)
            if thread["freelancer_id"] != me["id"]:
                raise HTTPException(404, f"{thread_id} not found")
            msg = {"id": f"{thread_id}_m{len(thread['messages']) + 1}", "sender": "freelancer",
                   "body": body.body, "sent_at": _now()}
            thread["messages"].append(msg)
            return msg
        return once(me, idempotency_key, {"op": "message", "thread": thread_id, **body.model_dump()},
                    write)

    return app
