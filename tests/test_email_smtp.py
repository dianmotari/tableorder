"""SMTP OTP delivery tests (free Gmail SMTP path).

Mocks smtplib.SMTP so no real email is sent. Verifies the code is delivered via
STARTTLS + login, and that a broken SMTP server yields HTTP 503 (no OTP leak).
"""
import smtplib
import uuid

from fastapi.testclient import TestClient

from app import schema
from app.main import app

client = TestClient(app)


def _smtp_env(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "me@gmail.com")
    monkeypatch.setenv("SMTP_PASS", "app-password")
    monkeypatch.setenv("EMAIL_FROM", "me@gmail.com")
    monkeypatch.delenv("EMAIL_API_KEY", raising=False)


def test_smtp_otp_delivery(monkeypatch):
    schema.create_all()
    _smtp_env(monkeypatch)
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port):
            sent["host"] = host
            sent["port"] = port

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            sent["tls"] = True

        def login(self, user, password):
            sent["login"] = (user, password)

        def send_message(self, msg):
            sent["to"] = msg["To"]
            sent["subject"] = msg["Subject"]

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

    email = f"s_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/customer/request-otp", json={"email": email})
    assert r.status_code == 200
    assert sent["host"] == "smtp.gmail.com"
    assert sent["port"] == 587
    assert sent["tls"] is True
    assert sent["login"] == ("me@gmail.com", "app-password")
    assert sent["to"] == email
    assert sent["subject"] == "Your TableOrder verification code"


def test_smtp_failure_returns_503(monkeypatch):
    schema.create_all()
    _smtp_env(monkeypatch)

    class BoomSMTP:
        def __init__(self, *a, **k):
            raise RuntimeError("smtp down")

    monkeypatch.setattr(smtplib, "SMTP", BoomSMTP)

    email = f"b_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/customer/request-otp", json={"email": email})
    assert r.status_code == 503
    assert "dev_code" not in r.json()