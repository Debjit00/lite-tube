"""Authentication API endpoints (register, login, logout, current user)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.auth import (
    USERNAME_RE,
    create_session_token,
    get_current_user_optional,
    hash_password,
    pick_avatar_color,
    serialize_user,
    verify_password,
)
from app.config import SESSION_COOKIE_NAME, SESSION_TTL_SECONDS
from app.db import db_session

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterPayload(BaseModel):
    username: str
    display_name: str | None = None
    password: str


class LoginPayload(BaseModel):
    username: str
    password: str


def _set_session_cookie(response: Response, user_id: int) -> None:
    token = create_session_token(user_id)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterPayload, response: Response) -> dict[str, Any]:
    """Create a new creator account and establish a signed session cookie."""
    username = payload.username.strip()
    if not USERNAME_RE.match(username):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be 3-32 characters using letters, numbers, '_' or '-'.",
        )
    if len(payload.password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long.",
        )

    display_name = (payload.display_name or username).strip()[:48] or username
    now = datetime.now(timezone.utc).isoformat()
    password_hash = hash_password(payload.password)
    avatar_color = pick_avatar_color(username)

    with db_session() as conn:
        try:
            cursor = conn.execute(
                """
                INSERT INTO users (username, display_name, password_hash, avatar_color, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, display_name, password_hash, avatar_color, now),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="That username is already taken.",
            )
        row = conn.execute(
            "SELECT id, username, display_name, avatar_color, created_at FROM users WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()

    _set_session_cookie(response, row["id"])
    return {"user": serialize_user(row)}


@router.post("/login")
def login(payload: LoginPayload, response: Response) -> dict[str, Any]:
    """Verify credentials and issue a signed session cookie."""
    username = payload.username.strip()
    if not username or not payload.password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username and password are required.",
        )

    with db_session() as conn:
        row = conn.execute(
            """
            SELECT id, username, display_name, password_hash, avatar_color, created_at
            FROM users
            WHERE username = ?
            """,
            (username,),
        ).fetchone()

    if row is None or not verify_password(payload.password, row["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    _set_session_cookie(response, row["id"])
    return {"user": serialize_user(row)}


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    """Clear the session cookie."""
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict[str, Any]:
    """Return the signed-in user profile or null when browsing as a guest."""
    return {"user": get_current_user_optional(request)}
