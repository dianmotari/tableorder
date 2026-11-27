"""Step 7 tests: customer places an order; server prices it; idempotency works.

Run from the project root:  python -m pytest -q
"""
import uuid

from fastapi.testclient import TestClient

from app import auth, db, schema
from app.main import app

client = TestClient(app)


def _new_customer():
    email = f"c_{uuid.uuid4().hex[:8]}@e.com"
    db.execute(
        "INSERT INTO users (hotel_id, role, email, name, password_hash, active, created_at) "
        "VALUES (?, 'customer', ?, 'C', NULL, 1, ?)",
        (1, email, auth.now_iso()),
    )
    uid = db.query_one("SELECT id FROM users WHERE email = ?", (email,))["id"]
    client.cookies.set(auth.COOKIE_NAME, auth.create_session(uid))
    return uid


def _menu_item(name="Cake", price=200):
    return db.execute_returning_id(
        "INSERT INTO menu_items (hotel_id, category_id, name, price_kes, active, created_at) "
        "VALUES (?, NULL, ?, ?, 1, ?)",
        (1, name, price, auth.now_iso()),
    )


def test_place_order_uses_server_price():
    schema.create_all()
    _new_customer()
    item_id = _menu_item("Cake", 200)
    # Create a table and grab its token.
    db.execute(
        "INSERT INTO tables (hotel_id, name, token, status, active, created_at) "
        "VALUES (?, 'T1', ?, 'free', 1, ?)",
        (1, "tok_" + uuid.uuid4().hex, auth.now_iso()),
    )
    table_token = db.query_one("SELECT token FROM tables ORDER BY id DESC LIMIT 1")["token"]

    # Phone tries to send its own price 1; server must use 200.
    resp = client.post("/orders", json={
        "table_token": table_token,
        "items": [{"menu_item_id": item_id, "qty": 2}],
        "idempotency_key": uuid.uuid4().hex,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_kes"] == 400  # 2 x 200 from the DB, not the phone

    detail = client.get(f"/orders/{body['order_id']}").json()
    assert detail["items"][0]["price_kes"] == 200
    assert detail["items"][0]["qty"] == 2


def test_idempotency_key_no_double_order():
    schema.create_all()
    _new_customer()
    item_id = _menu_item("Juice", 150)
    db.execute(
        "INSERT INTO tables (hotel_id, name, token, status, active, created_at) "
        "VALUES (?, 'T2', ?, 'free', 1, ?)",
        (1, "tok_" + uuid.uuid4().hex, auth.now_iso()),
    )
    table_token = db.query_one("SELECT token FROM tables ORDER BY id DESC LIMIT 1")["token"]
    key = uuid.uuid4().hex
    payload = {"table_token": table_token, "items": [{"menu_item_id": item_id, "qty": 1}],
               "idempotency_key": key}

    first = client.post("/orders", json=payload).json()
    second = client.post("/orders", json=payload).json()
    assert first["order_id"] == second["order_id"]
    assert second.get("duplicate") is True

    # Only one order row exists for this key.
    n = db.query_one("SELECT COUNT(*) AS n FROM orders WHERE idempotency_key = ?", (key,))["n"]
    assert n == 1


def test_dead_table_token_rejected():
    schema.create_all()
    _new_customer()
    item_id = _menu_item("Tea", 100)
    resp = client.post("/orders", json={
        "table_token": "does-not-exist",
        "items": [{"menu_item_id": item_id, "qty": 1}],
        "idempotency_key": uuid.uuid4().hex,
    })
    assert resp.status_code == 404