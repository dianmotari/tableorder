"""Send the one-time code by email.

Order of preference (checked at call time via environment variables):
1. Gmail/any SMTP  -> smtplib with STARTTLS + login (works with free Gmail).
2. Resend HTTP API -> when EMAIL_API_KEY is set.
3. Local dev       -> print the code to the server console (for unit tests).

On a real send failure we raise; the caller returns HTTP 503 (never leaks OTP).
Keys/passwords stay in .env / host env vars only - never in chat.
"""
import os
import smtplib
from email.message import EmailMessage

import httpx

RESEND_URL = "https://api.resend.com/emails"


def _smtp_settings():
    host = os.getenv("SMTP_HOST", "").strip()
    user = os.getenv("SMTP_USER", "").strip()
    password = (os.getenv("SMTP_PASS") or os.getenv("SMTP_PASSWORD") or "").strip()
    port = os.getenv("SMTP_PORT", "587").strip() or "587"
    return host, user, password, port


def _send_smtp(email: str, code: str, host, user, password, port) -> bool:
    msg = EmailMessage()
    msg["Subject"] = "Your TableOrder verification code"
    msg["From"] = os.getenv("EMAIL_FROM", "").strip() or user
    msg["To"] = email
    msg.set_content(f"Your one-time code is: {code}\nIt expires in 10 minutes.")
    try:
        with smtplib.SMTP(host, int(port)) as s:
            s.starttls()
            if user:
                s.login(user, password)
            s.send_message(msg)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"SMTP error: {exc}")
    return True


def _send_resend(email: str, code: str) -> bool:
    api_key = os.getenv("EMAIL_API_KEY", "").strip()
    from_addr = os.getenv("EMAIL_FROM", "").strip()
    if not from_addr:
        raise RuntimeError("EMAIL_FROM is not configured.")
    html = (
        f"<p>Your TableOrder verification code is "
        f"<strong style='font-size:20px'>{code}</strong>.</p>"
        f"<p>It expires in 10 minutes.</p>"
    )
    payload = {
        "from": from_addr,
        "to": [email],
        "subject": "Your TableOrder verification code",
        "html": html,
    }
    try:
        r = httpx.post(
            RESEND_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Could not reach the email service: {exc}")
    if r.status_code >= 300:
        raise RuntimeError(f"Email provider error {r.status_code}: {r.text}")
    return True


def send_otp(email: str, code: str) -> bool:
    """Send the OTP. Raises RuntimeError on a real delivery failure."""
    host, user, password, port = _smtp_settings()
    if host and user and password:
        return _send_smtp(email, code, host, user, password, port)
    if os.getenv("EMAIL_API_KEY", "").strip():
        return _send_resend(email, code)
    # Local dev / unit tests: print the code, do not fail.
    print(f"[OTP] code for {email}: {code}")
    return True