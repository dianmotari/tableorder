"""Authentication helpers: passwords, sessions, and role checks.

- Passwords (staff) are hashed with bcrypt. We never store plain passwords.
- Sessions use a random token in an HttpOnly cookie. The database stores only
  the SHA-256 HASH of the token, so a database leak cannot be reused to log in.
- require_roles(...) is a FastAPI dependency that blocks anyone whose role is
  not allowed. Put it on EVERY protected route (server is the source of truth).
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Depends, HTTPException, Request, status

from . import db
from .config import settings

COOKIE_NAME = "session"
_SESSION_DAYS = 30


# --- time helpers (store/compare ISO-8601 UTC text) -------------------------
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_future(iso_str: str) -> bool:
    try:
        return datetime.fromisoformat(iso_str) > datetime.now(timezone.utc)
    except Exception:
        return False


# --- passwords --------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False


# --- sessions ---------------------------------------------------------------
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: int) -> str:
    """Create a session row (storing the hash) and return the raw token."""
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=_SESSION_DAYS)).isoformat()
    db.execute(
        "INSERT INTO sessions (user_id, token_hash, created_at, expires_at) "
        "VALUES (?, ?, ?, ?)",
        (user_id, _hash_token(token), now_iso(), expires),
    )
    return token


def session_user(token: str):
    """Return the user dict for a valid, unexpired session token, else None."""
    if not token:
        return None
    row = db.query_one(
        "SELECT u.id, u.hotel_id, u.role, u.email, u.name, u.active, "
        "u.must_change_password, s.expires_at "
        "FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token_hash = ?",
        (_hash_token(token),),
    )
    if not row or not row.get("active"):
        return None
    if not _is_future(row["expires_at"]):
        return None
    return row


def delete_session(token: str):
    if token:
        db.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash_token(token),))


# --- request dependencies ---------------------------------------------------
def current_user(request: Request):
    """Return the logged-in user or raise 401. Use on every protected route."""
    token = request.cookies.get(COOKIE_NAME)
    user = session_user(token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not signed in")
    return user


def require_roles(*roles):
    """Dependency factory: allow only the given roles, else 403.

    Example:  @router.get("/admin/x", dependencies=[Depends(require_roles("admin"))])
    """
    allowed = set(roles)

    def _dep(user=Depends(current_user)):
        if user["role"] not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Wrong role")
        return user

    return _dep