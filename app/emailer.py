"""Send the one-time code by email.

If SMTP is configured in .env we send a real email. Otherwise (local dev) we
print the code to the server console so you can test without an email account.
Keys stay in .env only - never in chat.
"""
import smtplib
from email.message import EmailMessage

from .config import settings


def send_otp(email: str, code: str) -> bool:
    """Send the OTP. Returns True if a real email was sent, False if only printed."""
    if not settings.SMTP_HOST:
        # Development fallback: show the code in the terminal running uvicorn.
        print(f"[OTP] code for {email}: {code}")
        return False

    msg = EmailMessage()
    msg["Subject"] = "Your TableOrder code"
    msg["From"] = settings.EMAIL_FROM or settings.SMTP_USER
    msg["To"] = email
    msg.set_content(f"Your one-time code is: {code}\nIt expires in 10 minutes.")

    with smtplib.SMTP(settings.SMTP_HOST, int(settings.SMTP_PORT or 587)) as s:
        s.starttls()
        if settings.SMTP_USER:
            s.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        s.send_message(msg)
    return True