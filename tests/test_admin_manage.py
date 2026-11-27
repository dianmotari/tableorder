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