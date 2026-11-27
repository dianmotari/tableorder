"""Step 3 tests: admin login works and role checks block the wrong role.

Run from the project root:  python -m pytest -q
"""
import uuid

from fastapi.testclient import TestClient

from app import auth, db, schema
from app.main import app

client = TestClient(app)


def _make_user(role: str, email: str, password: str) -> int:
    db.execute(
        "INSERT INTO users (hotel_id, role, email, name, password_hash, active, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?)",
        (1, role, email, "Test", auth.hash_password(password), auth.now_iso()),
    )
    row = db.query_one("SELECT id FROM users WHERE email = ?", (email,))
    return row["id"]


def test_admin_login_and_ping():
    schema.create_all()
    email = f"admin_{uuid.uuid4().hex[:8]}@example.com"
    pw = "secret123"
    _make_user("admin", email, pw)

    # Wrong password is rejected.
    bad = client.post("/admin/login", json={"email": email, "password": "nope"})
    assert bad.status_code == 401

    # Correct password sets a cookie and returns ok.
    good = client.post("/admin/login", json={"email": email, "password": pw})
    assert good.status_code == 200
    assert good.json()["ok"] is True

    # The protected admin route now works.
    ping = client.get("/admin/ping")
    assert ping.status_code == 200
    assert ping.json()["role"] == "admin"


def test_customer_cannot_reach_admin():
    schema.create_all()
    # A customer session must get 403 on an admin-only route.
    uid = _make_user("customer", f"c_{uuid.uuid4().hex[:8]}@example.com", "x")
    token = auth.create_session(uid)
    client.cookies.set(auth.COOKIE_NAME, token)

    resp = client.get("/admin/ping")
    assert resp.status_code == 403
    client.cookies.clear()


def test_no_session_is_401():
    client.cookies.clear()
    assert client.get("/admin/ping").status_code == 401