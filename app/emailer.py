"""Send the one-time code by email using Resend (HTTPS API).

No dev auto-fill: if the API key is missing or Resend rejects the request we
raise, and the caller returns an error to the client instead of leaking the OTP.
Keys stay in .env / host env vars only - never in chat.
"""
import httpx

from .config import settings

RESEND_URL = "https://api.resend.com/emails"


def send_otp(email: str, code: str) -> bool:
    """Send the OTP via Resend. Raises RuntimeError on any failure."""
    if not settings.EMAIL_API_KEY:
        raise RuntimeError("Email service is not configured (EMAIL_API_KEY missing).")
    if not settings.EMAIL_FROM:
        raise RuntimeError("EMAIL_FROM is not configured.")

    html = (
        f"<p>Your TableOrder verification code is "
        f"<strong style='font-size:20px'>{code}</strong>.</p>"
        f"<p>It expires in 10 minutes.</p>"
    )
    payload = {
        "from": settings.EMAIL_FROM,
        "to": [email],
        "subject": "Your TableOrder verification code",
        "html": html,
    }
    try:
        r = httpx.post(
            RESEND_URL,
            headers={
                "Authorization": f"Bearer {settings.EMAIL_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
    except Exception as exc:  # network error
        raise RuntimeError(f"Could not reach the email service: {exc}")

    if r.status_code >= 300:
        # Do not leak the code; surface the provider's error message.
        raise RuntimeError(f"Email provider error {r.status_code}: {r.text}")
    return True