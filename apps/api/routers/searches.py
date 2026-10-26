"""Saved searches: the worker runs them on their own schedule (15 minutes minimum)."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from apps.api import db
from apps.api.auth import User
from apps.api.schemas import SearchIn, SearchOut

router = APIRouter(prefix="/searches", tags=["searches"])
COLUMNS = "id, query, skills, every_minutes, enabled, last_run_at"


@router.get("", response_model=list[SearchOut], operation_id="searches_list")
async def list_searches(user: User, request: Request):
    return await db.fetch(request.app.state.db, f"SELECT {COLUMNS} FROM saved_searches "
                          "WHERE user_id = %s ORDER BY created_at", user["id"])


@router.post("", response_model=SearchOut, status_code=201)
async def create(body: SearchIn, user: User, request: Request):
    return await db.fetchone(
        request.app.state.db,
        f"INSERT INTO saved_searches (user_id, query, skills, every_minutes) "
        f"VALUES (%s, %s, %s, %s) RETURNING {COLUMNS}",
        user["id"], body.query, body.skills, body.every_minutes)


@router.delete("/{search_id}", status_code=204)
async def delete(search_id: UUID, user: User, request: Request):
    if not await db.fetchone(request.app.state.db, "DELETE FROM saved_searches WHERE id = %s "
                             "AND user_id = %s RETURNING id", search_id, user["id"]):
        raise HTTPException(404, "search not found")
