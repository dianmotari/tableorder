"""Step 4 tests: tables CRUD, soft-delete kills the token, regenerate dies.

Covers the acceptance checks:
- deleting a table kills its QR link
- regenerating makes the old printed code stop working

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
    r = client.post("/admin/login", json={"email": email, "password": "pw"})
    assert r.status_code == 200


def test_add_list_and_token_landing():
    schema.create_all()
    _login_admin()

    created = client.post("/admin/tables", json={"name": "Table 1", "seats": 4})
    assert created.status_code == 201
    token = created.json()["token"]
    assert len(token) >= 16  # unguessable

    listing = client.get("/admin/tables")
    assert any(t["token"] == token for t in listing.json())

    # Public landing works with a valid token.
    land = client.get(f"/t/{token}")
    assert land.status_code == 200
    assert land.json()["valid"] is True


def test_soft_delete_kills_token():
    schema.create_all()
    _login_admin()
    token = client.post("/admin/tables", json={"name": "Table X"}).json()["token"]
    tid = client.get("/admin/tables").json()[-1]["id"]

    assert client.get(f"/t/{token}").status_code == 200
    assert client.delete(f"/admin/tables/{tid}").status_code == 200
    # After soft-delete the QR link is dead.
    assert client.get(f"/t/{token}").status_code == 404


def test_regenerate_invalidates_old_token():
    schema.create_all()
    _login_admin()
    old = client.post("/admin/tables", json={"name": "Table Y"}).json()["token"]
    tid = client.get("/admin/tables").json()[-1]["id"]

    new = client.post(f"/admin/tables/{tid}/regenerate").json()["token"]
    assert new != old
    # Old printed code stops working; new one works.
    assert client.get(f"/t/{old}").status_code == 404
    assert client.get(f"/t/{new}").status_code == 200


def test_print_pages_render():
    schema.create_all()
    _login_admin()
    client.post("/admin/tables", json={"name": "Table Z"})
    one = client.get("/admin/tables/print/all")
    assert one.status_code == 200
    assert "qr-code-styling" in one.text
    assert "Scan to order" in one.text


def test_non_admin_cannot_manage_tables():
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

    # A customer must not be able to add tables.
    resp = client.post("/admin/tables", json={"name": "Nope"})
    assert resp.status_code == 403
    client.cookies.clear()


def test_qr_uses_static_customer_url():
    schema.create_all()
    _login_admin()
    token = client.post("/admin/tables", json={"name": "Table Q"}).json()["token"]
    page = client.get("/admin/tables/print/all")
    assert page.status_code == 200
    # QR must point at /static/customer.html (not the bare /customer.html).
    assert f"/static/customer.html?token={token}" in page.text


def test_customer_html_redirect_preserves_token():
    client.cookies.clear()
    r = client.get("/customer.html?token=abc123", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/static/customer.html?token=abc123"


def test_admin_and_waiter_html_redirects():
    client.cookies.clear()
    for name in ("admin.html", "waiter.html"):
        r = client.get(f"/{name}", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == f"/static/{name}"