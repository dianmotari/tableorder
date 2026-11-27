"""Step 9 + password-flow tests: waiter login, forced password change,
dashboard grouping, mark served, finish table.

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


def _create_waiter(name="Mary"):
    r = client.post("/admin/waiters", json={
        "name": name, "email": f"m_{uuid.uuid4().hex[:8]}@e.com"})
    assert r.status_code == 201
    return r.json()  # has id, email, temp_password


def _setup_table_with_order(guest="Guest 1"):
    token = "tok_" + uuid.uuid4().hex
    tid = db.execute_returning_id(
        "INSERT INTO tables (hotel_id, name, token, status, active, created_at) "
        "VALUES (?, 'T', ?, 'free', 1, ?)", (1, token, auth.now_iso()))
    sid = db.execute_returning_id(
        "INSERT INTO table_sessions (hotel_id, table_id, status, opened_at) "
        "VALUES (?, ?, 'open', ?)", (1, tid, auth.now_iso()))
    oid = db.execute_returning_id(
        "INSERT INTO orders (hotel_id, table_id, session_id, user_id, guest_label, status, created_at) "
        "VALUES (?, ?, ?, NULL, ?, 'placed', ?)", (1, tid, sid, guest, auth.now_iso()))
    iid = db.execute_returning_id(
        "INSERT INTO order_items (order_id, menu_item_id, name_snapshot, price_kes, qty, status) "
        "VALUES (?, NULL, 'Cake', 200, 1, 'placed')", (oid,))
    return tid, iid


def test_temp_password_and_forced_change():
    schema.create_all()
    _admin_login()
    w = _create_waiter()
    temp = w["temp_password"]
    assert len(temp) == 8  # auto-generated, 8 chars

    # Login with the temp password works, and flags must_change_password.
    client.cookies.clear()
    login = client.post("/waiter/login", json={"email": w["email"], "password": temp})
    assert login.status_code == 200
    assert login.json()["must_change_password"] is True

    # Waiter actions are blocked until the password is changed.
    assert client.get("/waiter/dashboard").status_code == 403

    # Wrong current password is rejected.
    assert client.post("/waiter/change-password", json={
        "current_password": "nope", "new_password": "newpass1"}).status_code == 400

    # Change the password.
    ok = client.post("/waiter/change-password", json={
        "current_password": temp, "new_password": "newpass1"})
    assert ok.status_code == 200

    # Now the dashboard is allowed.
    assert client.get("/waiter/dashboard").status_code == 200
    assert client.get("/waiter/me").json()["must_change_password"] is False


def test_login_with_new_password():
    schema.create_all()
    _admin_login()
    w = _create_waiter()
    temp = w["temp_password"]

    client.cookies.clear()
    client.post("/waiter/login", json={"email": w["email"], "password": temp})
    client.post("/waiter/change-password", json={
        "current_password": temp, "new_password": "brandnew2"})

    # Old temp password no longer works; new one does.
    client.cookies.clear()
    assert client.post("/waiter/login", json={"email": w["email"], "password": temp}).status_code == 401
    r = client.post("/waiter/login", json={"email": w["email"], "password": "brandnew2"})
    assert r.status_code == 200
    assert r.json()["must_change_password"] is False


def test_waiter_dashboard_and_finish():
    schema.create_all()
    _admin_login()
    w = _create_waiter()
    wid = w["id"]

    tid, iid = _setup_table_with_order("Guest 1")
    queue.assign_table(tid, wid, admin_id=1)

    # Log in and clear the forced change.
    client.cookies.clear()
    client.post("/waiter/login", json={"email": w["email"], "password": w["temp_password"]})
    client.post("/waiter/change-password", json={
        "current_password": w["temp_password"], "new_password": "served123"})

    dash = client.get("/waiter/dashboard").json()
    assert dash["table"]["id"] == tid
    assert dash["guests"][0]["guest"] == "Guest 1"

    assert client.post(f"/waiter/items/{iid}/served").status_code == 200
    assert client.post("/waiter/finish").status_code == 200
    assert client.get("/waiter/me").json()["status"] == "free"


def test_customer_cannot_use_waiter_api():
    schema.create_all()
    email = f"c_{uuid.uuid4().hex[:8]}@e.com"
    db.execute(
        "INSERT INTO users (hotel_id, role, email, name, active, created_at) "
        "VALUES (?, 'customer', ?, 'C', 1, ?)", (1, email, auth.now_iso()))
    uid = db.query_one("SELECT id FROM users WHERE email = ?", (email,))["id"]
    client.cookies.clear()
    client.cookies.set(auth.COOKIE_NAME, auth.create_session(uid))
    assert client.get("/waiter/dashboard").status_code == 403
    client.cookies.clear()