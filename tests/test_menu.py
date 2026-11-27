"""Step 5 tests: menu CRUD (admin) and public menu (active items only).

Run from the project root:  python -m pytest -q
"""
import uuid

from fastapi.testclient import TestClient

from app import auth, db, schema
from app.main import app

client = TestClient(app)


def _login_admin():
    email = f"admin_{uuid.uuid4().hex[:8]}@example.com"
    db.execute(
        "INSERT INTO users (hotel_id, role, email, name, password_hash, active, created_at) "
        "VALUES (?, 'admin', ?, 'A', ?, 1, ?)",
        (1, email, auth.hash_password("pw"), auth.now_iso()),
    )
    assert client.post("/admin/login", json={"email": email, "password": "pw"}).status_code == 200


def test_category_and_item_crud():
    schema.create_all()
    _login_admin()

    cat = client.post("/admin/categories", json={"name": "Mains", "sort_order": 1})
    assert cat.status_code == 201
    cat_id = cat.json()["id"]

    item = client.post("/admin/menu", json={
        "name": "Ugali + Beef", "category_id": cat_id, "price_kes": 350,
        "description": "with greens",
    })
    assert item.status_code == 201
    item_id = item.json()["id"]

    # Public menu shows active items with the server-set price.
    menu = client.get("/menu").json()
    names = [i["name"] for i in menu["items"]]
    assert "Ugali + Beef" in names
    beef = next(i for i in menu["items"] if i["id"] == item_id)
    assert beef["price_kes"] == 350

    # Edit price.
    client.patch(f"/admin/menu/{item_id}", json={
        "name": "Ugali + Beef", "category_id": cat_id, "price_kes": 400, "active": True,
    })
    beef = next(i for i in client.get("/menu").json()["items"] if i["id"] == item_id)
    assert beef["price_kes"] == 400

    # Soft-delete hides it from the public menu.
    client.delete(f"/admin/menu/{item_id}")
    assert all(i["id"] != item_id for i in client.get("/menu").json()["items"])


def test_negative_price_rejected():
    schema.create_all()
    _login_admin()
    r = client.post("/admin/menu", json={"name": "Bad", "price_kes": -5})
    assert r.status_code == 400


def test_customer_cannot_edit_menu():
    schema.create_all()
    email = f"c_{uuid.uuid4().hex[:8]}@e.com"
    db.execute(
        "INSERT INTO users (hotel_id, role, email, name, password_hash, active, created_at) "
        "VALUES (?, 'customer', ?, 'C', ?, 1, ?)",
        (1, email, auth.hash_password("x"), auth.now_iso()),
    )
    uid = db.query_one("SELECT id FROM users WHERE email = ?", (email,))["id"]
    client.cookies.clear()
    client.cookies.set(auth.COOKIE_NAME, auth.create_session(uid))
    assert client.post("/admin/menu", json={"name": "x", "price_kes": 1}).status_code == 403
    client.cookies.clear()