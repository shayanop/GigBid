from fastapi import APIRouter, HTTPException, Request
from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb

from apps.api import db
from apps.api.auth import User, hash_password, password_matches
from apps.api.schemas import Credentials, Settings, Signup, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserOut, status_code=201)
async def signup(body: Signup, request: Request):
    # ponytail: the account is taken on trust; marketplace OAuth verifies it in live mode.
    try:
        user = await db.fetchone(
            request.app.state.db,
            "INSERT INTO users (email, password_hash, account) VALUES (lower(%s), %s, %s) "
            "RETURNING id, email, account, settings",
            body.email, hash_password(body.password), body.account)
    except UniqueViolation:
        raise HTTPException(409, "email already registered") from None
    request.session["uid"] = str(user["id"])
    return user


@router.post("/login", response_model=UserOut)
async def login(body: Credentials, request: Request):
    user = await db.fetchone(
        request.app.state.db,
        "SELECT id, email, account, settings, password_hash FROM users WHERE email = lower(%s)",
        body.email)
    if not user or not password_matches(user["password_hash"], body.password):
        raise HTTPException(401, "wrong email or password")
    request.session["uid"] = str(user["id"])
    return user


@router.post("/logout", status_code=204)
async def logout(request: Request):
    request.session.clear()


@router.get("/me", response_model=UserOut)
async def me(user: User):
    return user


@router.put("/me/settings", response_model=UserOut)
async def update_settings(body: Settings, user: User, request: Request):
    return await db.fetchone(
        request.app.state.db, "UPDATE users SET settings = %s WHERE id = %s "
                              "RETURNING id, email, account, settings",
        Jsonb(body.model_dump(exclude_none=True)), user["id"])
