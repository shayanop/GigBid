"""Users and sessions: argon2 password hashes, signed session cookie holding the user id.
The encrypted marketplace OAuth token store arrives with the live Upwork adapter."""

from typing import Annotated

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request

from apps.api import db

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def password_matches(stored: str, password: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except VerificationError:
        return False


async def current_user(request: Request) -> dict:
    uid = request.session.get("uid")
    user = uid and await db.fetchone(
        request.app.state.db, "SELECT id, email, account, settings FROM users WHERE id = %s", uid)
    if not user:
        request.session.clear()
        raise HTTPException(401, "sign in required")
    return user


User = Annotated[dict, Depends(current_user)]
