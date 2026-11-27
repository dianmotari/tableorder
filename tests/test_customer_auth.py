"""Step 6 tests: customer email OTP sign-in and role isolation.

We capture the OTP by replacing emailer.send_otp (no real email in tests).

Run from the project root:  python -m pytest -q
"""
import uuid

from fastapi.testclient import TestClient

from app import auth, db, schema
from app.main import app
from app.routers import customer as customer_mod

client = TestClient(app)


def _capture_otp(monkeypatch):
    box = {}
    def fake_send(email, code):
        box["code"] = code
        return False
    monkeypatch.setattr(customer_mod.emailer, "send_otp", fake_send)
    return box


def test_otp_signin_and_cookie(monkeypatch):
    schema.create_all()
    box = _capture_otp(monkeypatch)
    email = f"g_{uuid.uuid4().hex[:8]}@example.com"

    req = client.post("/customer/request-otp", json={"email": email})
    assert req.status_code == 200
    code = box["code"]
    assert len(code) == 6

    # Wrong code fails.
    assert client.post("/customer/verify-otp", json={"email": email, "code": "000000"}).status_code == 400

    # Correct code signs in and sets a session cookie.
    ok = client.post("/customer/verify-otp", json={"email": email, "code": code})
    assert ok.status_code == 200
    me = client.get("/customer/me")
    assert me.status_code == 200
    assert me.json()["role"] == "customer"


def test_otp_rate_limit_three_per_hour(monkeypatch):
    schema.create_all()
    _capture_otp(monkeypatch)
    email = f"r_{uuid.uuid4().hex[:8]}@example.com"
    for _ in range(3):
        assert client.post("/customer/request-otp", json={"email": email}).status_code == 200
    # 4th in the same hour is blocked.
    assert client.post("/customer/request-otp", json={"email": email}).status_code == 429


def test_customer_cannot_reach_admin():
    schema.create_all()
    email = f"c_{uuid.uuid4().hex[:8]}@example.com"
    db.execute(
        "INSERT INTO users (hotel_id, role, email, name, password_hash, active, created_at) "
        "VALUES (?, 'customer', ?, 'C', NULL, 1, ?)",
        (1, email, auth.now_iso()),
    )
    uid = db.query_one("SELECT id FROM users WHERE email = ?", (email,))["id"]
    client.cookies.clear()
    client.cookies.set(auth.COOKIE_NAME, auth.create_session(uid))
    assert client.get("/admin/ping").status_code == 403
    client.cookies.clear()