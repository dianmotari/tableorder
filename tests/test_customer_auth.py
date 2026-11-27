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


def test_request_otp_error_when_email_fails(monkeypatch):
    schema.create_all()
    # A provider/config failure must return an error, never leak the code.
    def boom(email, code):
        raise RuntimeError("Email service is not configured (EMAIL_API_KEY missing).")
    monkeypatch.setattr(customer_mod.emailer, "send_otp", boom)

    email = f"f_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/customer/request-otp", json={"email": email})
    assert r.status_code == 503
    assert "dev_code" not in r.json()


def test_request_otp_success_has_no_dev_code(monkeypatch):
    schema.create_all()
    box = _capture_otp(monkeypatch)  # capture code, no real email
    email = f"g_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/customer/request-otp", json={"email": email})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "dev_code" not in body
    assert len(box["code"]) == 6


def test_otp_consumed_is_integer_and_blocks_reuse(monkeypatch):
    schema.create_all()
    box = _capture_otp(monkeypatch)
    email = f"h_{uuid.uuid4().hex[:8]}@example.com"
    assert client.post("/customer/request-otp", json={"email": email}).status_code == 200
    code = box["code"]

    # Stored as integer 0 (not boolean).
    row = db.query_one(
        "SELECT consumed FROM otp_codes WHERE email = ? ORDER BY id DESC LIMIT 1", (email,))
    assert row["consumed"] == 0

    # Correct code verifies and flips consumed to integer 1.
    assert client.post("/customer/verify-otp", json={"email": email, "code": code}).status_code == 200
    row = db.query_one(
        "SELECT consumed FROM otp_codes WHERE email = ? ORDER BY id DESC LIMIT 1", (email,))
    assert row["consumed"] == 1

    # A consumed code cannot be reused.
    client.cookies.clear()
    assert client.post("/customer/verify-otp", json={"email": email, "code": code}).status_code == 400


def test_new_customer_profile_then_returning(monkeypatch):
    schema.create_all()
    box = _capture_otp(monkeypatch)
    email = f"n_{uuid.uuid4().hex[:8]}@example.com"

    # First sign-in: new user, no profile yet.
    client.cookies.clear()
    assert client.post("/customer/request-otp", json={"email": email}).status_code == 200
    r = client.post("/customer/verify-otp", json={"email": email, "code": box["code"]})
    assert r.status_code == 200
    assert r.json()["is_new_user"] is True

    # Complete the profile.
    prof = client.post("/customer/profile", json={"full_name": "Jane Doe", "phone": "0712345678"})
    assert prof.status_code == 200

    # Second sign-in: returning customer with saved profile.
    client.cookies.clear()
    assert client.post("/customer/request-otp", json={"email": email}).status_code == 200
    r = client.post("/customer/verify-otp", json={"email": email, "code": box["code"]})
    assert r.status_code == 200
    body = r.json()
    assert body["is_new_user"] is False
    assert body["customer"]["full_name"] == "Jane Doe"
    assert body["customer"]["phone"] == "0712345678"