"""Waiter phone dashboard: login, see assigned table, mark items served,
and press "I'm available" to finish the table.

A waiter sees ONLY their own assigned table (role + ownership checks on every
route). Orders are grouped per guest because families/groups order together.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from .. import auth, db, queue
from ..config import settings

router = APIRouter(prefix="/waiter", tags=["waiter"])


class LoginIn(BaseModel):
    email: str
    password: str


def _my_waiter(user):
    row = db.query_one("SELECT * FROM waiters WHERE user_id = ?", (user["id"],))
    if not row:
        raise HTTPException(status_code=403, detail="Not a waiter account")
    return row


def _require_pw_changed(user):
    """Block waiter actions until they have changed the temp password."""
    row = db.query_one("SELECT must_change_password FROM users WHERE id = ?", (user["id"],))
    if row and row["must_change_password"]:
        raise HTTPException(status_code=403, detail="You must change your password first")


@router.post("/login")
def login(body: LoginIn, response: Response):
    user = db.query_one(
        "SELECT id, email, password_hash, active, must_change_password FROM users "
        "WHERE email = ? AND role = 'waiter'",
        (body.email.lower().strip(),),
    )
    if not user or not user.get("active") or not auth.verify_password(
        body.password, user["password_hash"]
    ):
        raise HTTPException(status_code=401, detail="Wrong email or password")
    token = auth.create_session(user["id"])
    response.set_cookie(
        auth.COOKIE_NAME, token, httponly=True, samesite="lax",
        secure=settings.COOKIE_SECURE, max_age=30 * 24 * 3600,
    )
    return {"ok": True, "must_change_password": bool(user["must_change_password"])}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(auth.require_roles("waiter"))):
    w = _my_waiter(user)
    return {
        "id": user["id"], "name": user["name"], "waiter_id": w["id"], "status": w["status"],
        "must_change_password": bool(user.get("must_change_password")),
    }


class ChangePwIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: ChangePwIn, user=Depends(auth.require_roles("waiter"))):
    row = db.query_one("SELECT password_hash FROM users WHERE id = ?", (user["id"],))
    if not row or not auth.verify_password(body.current_password, row["password_hash"]):
        raise HTTPException(status_code=400, detail="Current password is wrong")
    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="New password must be at least 6 characters")
    db.execute(
        "UPDATE users SET password_hash = ?, must_change_password = FALSE WHERE id = ?",
        (auth.hash_password(body.new_password), user["id"]),
    )
    return {"ok": True}


@router.get("/dashboard")
def dashboard(user=Depends(auth.require_roles("waiter"))):
    """The waiter's current table with orders grouped per guest."""
    _require_pw_changed(user)
    w = _my_waiter(user)
    active = db.query_one(
        "SELECT * FROM assignments WHERE waiter_id = ? AND ended_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (w["id"],),
    )
    if not active:
        return {"status": w["status"], "table": None, "guests": []}

    table = db.query_one("SELECT id, name FROM tables WHERE id = ?", (active["table_id"],))
    orders = db.query_all(
        "SELECT id, guest_label, status, note, created_at FROM orders "
        "WHERE session_id = ? ORDER BY id",
        (active["session_id"],),
    )
    # Group orders per guest label (fallback 'Guest').
    guests = {}
    for o in orders:
        label = o.get("guest_label") or "Guest"
        o["items"] = db.query_all(
            "SELECT id, name_snapshot AS name, price_kes, qty, status "
            "FROM order_items WHERE order_id = ?",
            (o["id"],),
        )
        guests.setdefault(label, []).append(o)
    grouped = [{"guest": g, "orders": items} for g, items in guests.items()]
    return {"status": w["status"], "table": table, "guests": grouped}


@router.post("/items/{item_id}/served")
def mark_served(item_id: int, user=Depends(auth.require_roles("waiter"))):
    """Mark one order_item served, but only if it belongs to my active table."""
    _require_pw_changed(user)
    w = _my_waiter(user)
    active = db.query_one(
        "SELECT session_id FROM assignments WHERE waiter_id = ? AND ended_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (w["id"],),
    )
    if not active:
        raise HTTPException(status_code=403, detail="No active table")
    row = db.query_one(
        "SELECT oi.id FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "WHERE oi.id = ? AND o.session_id = ?",
        (item_id, active["session_id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Item not on your table")
    db.execute("UPDATE order_items SET status = 'served' WHERE id = ?", (item_id,))
    return {"ok": True}


@router.post("/finish")
def finish(user=Depends(auth.require_roles("waiter"))):
    """I'm available: close my table and free myself for the next one."""
    _require_pw_changed(user)
    w = _my_waiter(user)
    active = db.query_one(
        "SELECT table_id FROM assignments WHERE waiter_id = ? AND ended_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (w["id"],),
    )
    if not active:
        raise HTTPException(status_code=400, detail="No active table to finish")
    queue.finish_table(active["table_id"], w["id"])
    return {"ok": True, "status": "free"}