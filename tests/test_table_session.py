"""Table Session tests: host creation, guest pending/approval, pay-for totals,
checkout, and chat.

Run from the project root:  python -m pytest -q
"""
import uuid

from fastapi.testclient import TestClient

from app import auth, db, schema
from app.main import app

client = TestClient(app)


def _customer(name):
    email = f"{uuid.uuid4().hex[:8]}@e.com"
    uid = db.execute_returning_id(
        "INSERT INTO users (hotel_id, role, email, name, active, created_at) "
        "VALUES (1, 'customer', ?, ?, 1, ?)",
        (email, name, auth.now_iso()),
    )
    db.execute(
        "INSERT INTO customers (email, full_name, phone, created_at) VALUES (?, ?, ?, ?)",
        (email, name, "0712345678", auth.now_iso()),
    )
    return uid, email


def _login(uid):
    client.cookies.clear()
    client.cookies.set(auth.COOKIE_NAME, auth.create_session(uid))


def _table():
    token = "tok_" + uuid.uuid4().hex
    tid = db.execute_returning_id(
        "INSERT INTO tables (hotel_id, name, token, status, active, created_at) "
        "VALUES (1, 'T', ?, 'free', 1, ?)",
        (token, auth.now_iso()),
    )
    return tid, token


def _order_with_item(session_id, table_id, customer_id, price):
    oid = db.execute_returning_id(
        "INSERT INTO orders (hotel_id, table_id, session_id, user_id, status, created_at) "
        "VALUES (1, ?, ?, ?, 'placed', ?)",
        (table_id, session_id, customer_id, auth.now_iso()),
    )
    db.execute(
        "INSERT INTO order_items (order_id, menu_item_id, name_snapshot, price_kes, qty, status) "
        "VALUES (?, NULL, 'X', ?, 1, 'placed')",
        (oid, price),
    )
    return oid


def test_host_creation_and_guest_approval():
    schema.create_all()
    host_id, _ = _customer("Frank")
    guest_id, _ = _customer("Grace")
    tid, token = _table()

    # Host opens the table -> becomes approved host.
    _login(host_id)
    j = client.post("/table-session/join", json={"table_token": token}).json()
    assert j["role"] == "host" and j["status"] == "approved"
    sid = j["session_id"]

    # Guest joins -> pending, sees host name.
    _login(guest_id)
    j2 = client.post("/table-session/join", json={"table_token": token}).json()
    assert j2["role"] == "guest" and j2["status"] == "pending"
    assert j2["host_name"] == "Frank"

    # Host sees the pending request and approves it.
    _login(host_id)
    st = client.get("/table-session/state", params={"token": token}).json()
    assert st["is_host"] is True
    assert any(p["full_name"] == "Grace" for p in st["pending"])
    member_id = db.query_one(
        "SELECT id FROM table_session_members WHERE session_id = ? AND customer_id = ?",
        (sid, guest_id))["id"]
    assert client.post("/table-session/approve", json={"member_id": member_id, "approve": True}).status_code == 200

    # Guest is now an approved member.
    _login(guest_id)
    st = client.get("/table-session/state", params={"token": token}).json()
    assert any(m["full_name"] == "Grace" for m in st["members"])


def test_pay_for_totals_and_checkout():
    schema.create_all()
    host_id, _ = _customer("Host")
    guest_id, _ = _customer("Guest")
    tid, token = _table()

    _login(host_id)
    sid = client.post("/table-session/join", json={"table_token": token}).json()["session_id"]
    _login(guest_id)
    client.post("/table-session/join", json={"table_token": token})
    member_id = db.query_one(
        "SELECT id FROM table_session_members WHERE session_id = ? AND customer_id = ?",
        (sid, guest_id))["id"]
    _login(host_id)
    client.post("/table-session/approve", json={"member_id": member_id})

    # Orders: host 500, guest 300.
    _order_with_item(sid, tid, host_id, 500)
    _order_with_item(sid, tid, guest_id, 300)

    # Guest pays for host -> host's paid_by becomes guest.
    _login(guest_id)
    r = client.post("/table-session/pay-for", json={"target_customer_id": host_id}).json()
    assert r["covering"] is True

    st = client.get("/table-session/state", params={"token": token}).json()
    host = next(m for m in st["members"] if m["customer_id"] == host_id)
    guest = next(m for m in st["members"] if m["customer_id"] == guest_id)
    assert host["subtotal"] == 500 and guest["subtotal"] == 300
    assert host["paid_by_customer_id"] == guest_id

    # Guest checks out "mine": covers own 300 + host's 500 (paid_by guest).
    res = client.post("/table-session/checkout", json={"scope": "mine"}).json()
    assert res["session_closed"] is True  # all table orders now paid
    paid = db.query_all("SELECT status FROM orders WHERE session_id = ?", (sid,))
    assert all(o["status"] == "paid" for o in paid)


def test_table_chat():
    schema.create_all()
    host_id, _ = _customer("Host")
    tid, token = _table()
    _login(host_id)
    client.post("/table-session/join", json={"table_token": token})

    assert client.post("/table-session/chat", json={"message": "Anyone want water?"}).status_code == 200
    st = client.get("/table-session/state", params={"token": token}).json()
    assert any(m["message"] == "Anyone want water?" for m in st["messages"])


def test_guest_cannot_approve():
    schema.create_all()
    host_id, _ = _customer("Host")
    guest_id, _ = _customer("Guest")
    tid, token = _table()
    _login(host_id)
    sid = client.post("/table-session/join", json={"table_token": token}).json()["session_id"]
    _login(guest_id)
    client.post("/table-session/join", json={"table_token": token})
    member_id = db.query_one(
        "SELECT id FROM table_session_members WHERE session_id = ? AND customer_id = ?",
        (sid, guest_id))["id"]
    # A guest (not host) cannot approve.
    assert client.post("/table-session/approve", json={"member_id": member_id}).status_code == 403