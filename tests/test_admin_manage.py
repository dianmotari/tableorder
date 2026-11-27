"""Tests for admin management endpoints added for the admin page:
edit/delete waiter, edit category.

Run from the project root:  python -m pytest -q
"""
import uuid

from fastapi.testclient import TestClient

from app import auth, db, schema
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


def test_waiter_edit_and_delete():
    schema.create_all()
    _admin_login()
    w = client.post("/admin/waiters", json={
        "name": "Mary", "email": f"m_{uuid.uuid4().hex[:6]}@e.com", "password": "pw"}).json()
    wid = w["id"]

    # Edit name + status.
    r = client.patch(f"/admin/waiters/{wid}", json={"name": "Mary J.", "status": "on_break"})
    assert r.status_code == 200
    row = db.query_one(
        "SELECT u.name, w.status FROM waiters w JOIN users u ON u.id=w.user_id WHERE w.id = ?",
        (wid,))
    assert row["name"] == "Mary J." and row["status"] == "on_break"

    # Delete (soft): user disabled, waiter off_duty.
    assert client.delete(f"/admin/waiters/{wid}").status_code == 200
    row = db.query_one(
        "SELECT u.active, w.status FROM waiters w JOIN users u ON u.id=w.user_id WHERE w.id = ?",
        (wid,))
    assert row["active"] == 0 and row["status"] == "off_duty"


def test_category_edit():
    schema.create_all()
    _admin_login()
    cid = client.post("/admin/categories", json={"name": "Starters", "sort_order": 1}).json()["id"]
    r = client.patch(f"/admin/categories/{cid}", json={"name": "Appetizers", "sort_order": 2})
    assert r.status_code == 200
    row = db.query_one("SELECT name, sort_order FROM categories WHERE id = ?", (cid,))
    assert row["name"] == "Appetizers" and row["sort_order"] == 2


def test_duplicate_waiter_email_returns_409():
    schema.create_all()
    _admin_login()
    email = f"dup_{uuid.uuid4().hex[:8]}@e.com"
    first = client.post("/admin/waiters", json={"name": "A", "email": email})
    assert first.status_code == 201

    # Same email, different case -> 409 with the exact detail, no new row.
    second = client.post("/admin/waiters", json={"name": "B", "email": email.upper()})
    assert second.status_code == 409
    assert second.json()["detail"] == "A user with this email already exists"

    n = db.query_one(
        "SELECT COUNT(*) AS n FROM users WHERE LOWER(email) = ?", (email.lower(),))["n"]
    assert n == 1


def test_startup_dedupes_and_indexes_emails():
    schema.create_all()
    # Simulate legacy duplicates (same email, different case) directly in the DB.
    email = f"legacy_{uuid.uuid4().hex[:8]}@e.com"
    for _ in range(2):
        db.execute(
            "INSERT INTO users (hotel_id, role, email, name, active, created_at) "
            "VALUES (?, 'customer', ?, 'C', 1, ?)",
            (1, email.upper(), auth.now_iso()),
        )
    db.ensure_users_email_unique()
    n = db.query_one(
        "SELECT COUNT(*) AS n FROM users WHERE LOWER(email) = ?", (email.lower(),))["n"]
    assert n == 1