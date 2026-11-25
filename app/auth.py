"""Password hashing, signed session cookies, and FastAPI auth dependencies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from typing import Any

from fastapi import HTTPException, Request, status

from app.config import (
    AVATAR_COLORS,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    get_secret_key,
)
from app.db import db_session

USERNAME_RE = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")
PBKDF2_ITERATIONS = 210_000


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256 and a random 16-byte salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored PBKDF2-HMAC-SHA256 hash."""
    try:
        scheme, iter_str, salt_hex, hash_hex = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iter_str)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
    except (ValueError, TypeError):
        return False

    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def _sign_raw(raw_payload: str) -> str:
    key = get_secret_key().encode("utf-8")
    return hmac.new(key, raw_payload.encode("ascii"), hashlib.sha256).hexdigest()


def create_session_token(user_id: int) -> str:
    """Create a URL-safe HMAC-signed session token for a user ID."""
    payload = {"sub": user_id, "exp": int(time.time()) + SESSION_TTL_SECONDS}
    encoded = (
        base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("=")
    )
    return f"{encoded}.{_sign_raw(encoded)}"


def verify_session_token(token: str) -> int | None:
    """Validate signature and expiration of a session token, returning user_id or None."""
    if not token or "." not in token:
        return None
    encoded, signature = token.split(".", 1)
    if not hmac.compare_digest(signature, _sign_raw(encoded)):
        return None

    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        if int(payload.get("exp", 0)) <= int(time.time()):
            return None
        return int(payload["sub"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def pick_avatar_color(username: str) -> str:
    """Select a deterministic avatar color for a username."""
    total = sum(username.lower().encode("utf-8"))
    return AVATAR_COLORS[total % len(AVATAR_COLORS)]


def serialize_user(row: Any) -> dict[str, Any]:
    """Convert a SQLite user row to a public JSON-safe dictionary."""
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"],
        "avatar_color": row["avatar_color"],
        "created_at": row["created_at"],
    }


def get_current_user_optional(request: Request) -> dict[str, Any] | None:
    """Return the authenticated user dict if a valid session cookie is present."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user_id = verify_session_token(token) if token else None
    if user_id is None:
        return None

    with db_session() as conn:
        row = conn.execute(
            "SELECT id, username, display_name, avatar_color, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return serialize_user(row) if row else None


def require_current_user(request: Request) -> dict[str, Any]:
    """Require an authenticated user or raise 401 Unauthorized."""
    user = get_current_user_optional(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please sign in to continue.",
        )
    return user
