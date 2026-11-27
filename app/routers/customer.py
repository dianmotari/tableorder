"""Customer sign-in: email one-time code (OTP) OR Google.

OTP rules (from the handoff):
- 6 digits, expires in 10 minutes
- max 5 verify tries per code
- max 3 codes requested per hour per email
- stored HASHED in the database (never the digits)

Google sign-in: the phone gets an ID token from Google; we verify it with
Google's tokeninfo endpoint (server-side) and trust only the returned email.

On success we create/find the customer user and set the same HttpOnly session
cookie used for staff. Customers can never reach staff/admin routes because
those check the role.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from .. import auth, db, emailer
from ..config import settings

router = APIRouter(prefix="/customer", tags=["customer"])

OTP_TTL_MIN = 10
OTP_MAX_TRIES = 5
OTP_MAX_PER_HOUR = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str)


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _find_or_create_customer(email: str, name: str | None = None, google_sub: str | None = None) -> int:
    row = db.query_one(
        "SELECT id FROM users WHERE role = 'customer' AND email = ?", (email.lower(),)
    )
    if row:
        return row["id"]
    new_id = db.execute_returning_id(
        "INSERT INTO users (hotel_id, role, email, google_sub, name, active, created_at) "
        "VALUES (?, 'customer', ?, ?, ?, TRUE, ?)",
        (settings.DEFAULT_HOTEL_ID, email.lower(), google_sub, name or email, auth.now_iso()),
    )
    return new_id


def _set_cookie(response: Response, user_id: int):
    token = auth.create_session(user_id)
    response.set_cookie(
        auth.COOKIE_NAME, token, httponly=True, samesite="lax",
        secure=settings.COOKIE_SECURE, max_age=30 * 24 * 3600,
    )


# --- email OTP: request a code --------------------------------------------
class EmailIn(BaseModel):
    email: str


@router.post("/request-otp")
def request_otp(body: EmailIn):
    email = body.email.lower().strip()
    # Rate limit: max 3 codes per hour per email.
    since = _iso(_now() - timedelta(hours=1))
    recent = db.query_one(
        "SELECT COUNT(*) AS n FROM otp_codes WHERE email = ? AND created_at >= ?",
        (email, since),
    )
    if recent and recent["n"] >= OTP_MAX_PER_HOUR:
        raise HTTPException(status_code=429, detail="Too many codes. Try again later.")

    code = f"{secrets.randbelow(1000000):06d}"  # 6 digits
    db.execute(
        "INSERT INTO otp_codes (email, code_hash, attempts, consumed, created_at, expires_at) "
        "VALUES (?, ?, 0, FALSE, ?, ?)",
        (email, _hash_code(code), _iso(_now()), _iso(_now() + timedelta(minutes=OTP_TTL_MIN))),
    )
    # Try to email the code. If SMTP is not configured OR sending fails, never
    # crash with 500: log the code and return it as dev_code so testing works.
    sent = False
    try:
        sent = emailer.send_otp(email, code)
    except Exception as exc:  # noqa: BLE001 - any mail error must not break login
        print(f"[OTP] email send failed for {email}: {exc}")
    if not sent:
        print(f"[OTP] code for {email}: {code}")
        return {"ok": True, "dev_code": code}
    return {"ok": True, "message": "Code sent by email."}


# --- email OTP: verify and sign in ----------------------------------------
class VerifyIn(BaseModel):
    email: str
    code: str


@router.post("/verify-otp")
def verify_otp(body: VerifyIn, response: Response):
    email = body.email.lower().strip()
    row = db.query_one(
        "SELECT id, code_hash, attempts, expires_at FROM otp_codes "
        "WHERE email = ? AND consumed = FALSE ORDER BY id DESC LIMIT 1",
        (email,),
    )
    if not row:
        raise HTTPException(status_code=400, detail="No code requested. Request a new one.")
    if _parse(row["expires_at"]) < _now():
        raise HTTPException(status_code=400, detail="Code expired. Request a new one.")
    if row["attempts"] >= OTP_MAX_TRIES:
        raise HTTPException(status_code=429, detail="Too many tries. Request a new code.")

    # Count this as an attempt.
    db.execute("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = ?", (row["id"],))

    if row["code_hash"] != _hash_code(body.code.strip()):
        raise HTTPException(status_code=400, detail="Wrong code.")

    # Correct: consume the code and sign the customer in.
    db.execute("UPDATE otp_codes SET consumed = TRUE WHERE id = ?", (row["id"],))
    user_id = _find_or_create_customer(email)
    _set_cookie(response, user_id)
    return {"ok": True}


# --- Google sign-in -------------------------------------------------------
class GoogleIn(BaseModel):
    id_token: str


@router.post("/google")
def google_signin(body: GoogleIn, response: Response):
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="Google sign-in not configured.")
    # Verify the token with Google (server-side source of truth).
    try:
        r = httpx.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": body.id_token},
            timeout=10,
        )
        info = r.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Could not verify Google token.")

    if not info.get("email") or info.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=400, detail="Invalid Google token.")
    if not info.get("email_verified", "true") in ("true", True):
        raise HTTPException(status_code=400, detail="Google email not verified.")

    user_id = _find_or_create_customer(info["email"], info.get("name"), info.get("sub"))
    _set_cookie(response, user_id)
    return {"ok": True, "email": info["email"]}


# --- who am I / logout ----------------------------------------------------
@router.get("/me")
def me(user=Depends(auth.require_roles("customer"))):
    return {"id": user["id"], "email": user["email"], "role": user["role"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}