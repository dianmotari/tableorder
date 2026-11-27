"""Customer ordering: place an order and track it.

Server is the source of truth:
- Prices come from the menu_items table, NEVER from the phone.
- The table is validated from its unguessable token; a soft-deleted table is dead.
- An idempotency_key stops a double-submit (slow network) making two orders.
- Every order attaches to the table's current OPEN table_session, so several
  phones at one table share the session (and later the same waiter).

Stock/plates and the "table must be open" rule are Phase 2 - not enforced here.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db
from ..config import settings

router = APIRouter(prefix="/orders", tags=["orders"])


class LineIn(BaseModel):
    menu_item_id: int
    qty: int = 1


class OrderIn(BaseModel):
    table_token: str
    items: list[LineIn]
    guest_label: str | None = None
    note: str | None = None
    idempotency_key: str


def _valid_table(token: str):
    row = db.query_one(
        "SELECT id, hotel_id, status FROM tables WHERE token = ? AND active = 1", (token,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="This table code is not valid")
    return row


def _open_session(table_id: int) -> int:
    """Return the table's open session id, creating one if none is open."""
    row = db.query_one(
        "SELECT id FROM table_sessions WHERE table_id = ? AND status = 'open' "
        "ORDER BY id DESC LIMIT 1",
        (table_id,),
    )
    if row:
        return row["id"]
    return db.execute_returning_id(
        "INSERT INTO table_sessions (hotel_id, table_id, status, opened_at) "
        "VALUES (?, ?, 'open', ?)",
        (settings.DEFAULT_HOTEL_ID, table_id, auth.now_iso()),
    )


@router.post("")
def place_order(body: OrderIn, user=Depends(auth.require_roles("customer"))):
    if not body.items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    table = _valid_table(body.table_token)

    # Idempotency: if this key was already used, return the existing order.
    existing = db.query_one("SELECT id FROM orders WHERE idempotency_key = ?",
                            (body.idempotency_key,))
    if existing:
        return {"order_id": existing["id"], "duplicate": True}

    session_id = _open_session(table["id"])
    now = auth.now_iso()

    # Create the order header.
    order_id = db.execute_returning_id(
        "INSERT INTO orders "
        "(hotel_id, table_id, session_id, user_id, guest_label, status, note, "
        " idempotency_key, created_at) VALUES (?, ?, ?, ?, ?, 'placed', ?, ?, ?)",
        (
            settings.DEFAULT_HOTEL_ID, table["id"], session_id, user["id"],
            body.guest_label, body.note, body.idempotency_key, now,
        ),
    )

    # Add each line. Price + name are read from the DB (server truth), not the phone.
    total = 0
    for line in body.items:
        if line.qty <= 0:
            continue
        item = db.query_one(
            "SELECT name, price_kes FROM menu_items WHERE id = ? AND hotel_id = ? AND active = 1",
            (line.menu_item_id, settings.DEFAULT_HOTEL_ID),
        )
        if not item:
            raise HTTPException(status_code=400, detail=f"Item {line.menu_item_id} not available")
        db.execute(
            "INSERT INTO order_items (order_id, menu_item_id, name_snapshot, price_kes, qty, status) "
            "VALUES (?, ?, ?, ?, ?, 'placed')",
            (order_id, line.menu_item_id, item["name"], item["price_kes"], line.qty),
        )
        total += item["price_kes"] * line.qty

    return {"order_id": order_id, "total_kes": total, "status": "placed"}


@router.get("/mine")
def my_orders(user=Depends(auth.require_roles("customer"))):
    """The signed-in customer's orders, newest first, with their items."""
    orders = db.query_all(
        "SELECT id, table_id, status, note, created_at FROM orders "
        "WHERE user_id = ? ORDER BY id DESC",
        (user["id"],),
    )
    for o in orders:
        o["items"] = db.query_all(
            "SELECT name_snapshot AS name, price_kes, qty FROM order_items WHERE order_id = ?",
            (o["id"],),
        )
    return orders


@router.get("/{order_id}")
def order_detail(order_id: int, user=Depends(auth.require_roles("customer"))):
    order = db.query_one(
        "SELECT id, table_id, status, note, created_at FROM orders WHERE id = ? AND user_id = ?",
        (order_id, user["id"]),
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    order["items"] = db.query_all(
        "SELECT name_snapshot AS name, price_kes, qty, status FROM order_items WHERE order_id = ?",
        (order_id,),
    )
    return order