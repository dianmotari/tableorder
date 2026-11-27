"""Step 10 tests: admin board, assign, and reassign (with audit).

Run from the project root:  python -m pytest -q
"""
import uuid

from fastapi.testclient import TestClient

from app import auth, db, queue, schema
from app.main import app

client = TestClient(app)


def _admin_login():
    email = f"a_{uuid.uuid4().hex[:8]}@e.com"
    db.execute(
        "INSERT INTO users (hotel_id, role, email, name, password_hash, active, created_at) "
        "VALUES (?, 'admin', ?, 'A', ?, 1, ?)",
        (1, email, auth.hash_password("pw"), auth.now_iso()),
    )
    client.cookies.clear()
    assert client.post("/admin/login", json={"email": email, "password": "pw"}).status_code == 200
    return db.query_one("SELECT id FROM users WHERE email = ?", (email,))["id"]


def _waiter(name):
    email = f"w_{uuid.uuid4().hex[:8]}@e.com"
    uid = db.execute_returning_id(
        "INSERT INTO users (hotel_id, role, email, name, password_hash, active, created_at) "
        "VALUES (?, 'waiter', ?, ?, ?, 1, ?)",
        (1, email, name, auth.hash_password("x"), auth.now_iso()))
    wid = db.execute_returning_id(
        "INSERT INTO waiters (hotel_id, user_id, status) VALUES (?, ?, 'free')", (1, uid))
    return wid


def _waiting_table(name):
    tid = db.execute_returning_id(
        "INSERT INTO tables (hotel_id, name, token, status, active, created_at) "
        "VALUES (?, ?, ?, 'free', 1, ?)", (1, name, "t_" + uuid.uuid4().hex, auth.now_iso()))
    sid = db.execute_returning_id(
        "INSERT INTO table_sessions (hotel_id, table_id, status, opened_at) VALUES (?, ?, 'open', ?)",
        (1, tid, auth.now_iso()))
    db.execute(
        "INSERT INTO orders (hotel_id, table_id, session_id, status, created_at) "
        "VALUES (?, ?, ?, 'placed', ?)", (1, tid, sid, "2026-01-01T10:00:00+00:00"))
    return tid


def test_board_and_assign_flow():
    schema.create_all()
    _admin_login()
    tid = _waiting_table("A")
    wid = _waiter("Mary")

    b = client.get("/admin/board").json()
    assert any(w["table_id"] == tid for w in b["waiting"])
    assert any(fw["id"] == wid for fw in b["free_waiters"])

    r = client.post("/admin/assign", json={"table_id": tid, "waiter_id": wid})
    assert r.status_code == 200
    # Waiter is now busy and table no longer waiting.
    b = client.get("/admin/board").json()
    assert all(w["table_id"] != tid for w in b["waiting"])


def test_reassign_requires_reason_and_logs():
    schema.create_all()
    admin_id = _admin_login()
    tid = _waiting_table("A")
    w1 = _waiter("Mary")
    w2 = _waiter("John")
    queue.assign_table(tid, w1, admin_id=admin_id)

    # No reason -> 400.
    assert client.post("/admin/reassign", json={
        "table_id": tid, "waiter_id": w2}).status_code == 400

    # With reason -> ok and an audit row.
    r = client.post("/admin/reassign", json={
        "table_id": tid, "waiter_id": w2, "reason": "break"})
    assert r.status_code == 200
    logs = client.get("/admin/audit").json()
    assert any(l["action"] == "reassign" for l in logs)
    # w1 is free again, w2 now owns the table.
    active = queue.get_active_assignment(tid)
    assert active["waiter_id"] == w2