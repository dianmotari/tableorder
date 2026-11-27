"""Table Session system: host approval, shared members, split billing, chat.

A table has at most one OPEN session. The first customer to open the table (with
a complete profile) becomes the HOST; later customers join as GUESTS and must be
approved by the host. Approved members share the table's orders, can cover each
other's bills ("pay for"), chat, and settle (close the session once all paid).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .. import auth, db
from ..config import settings

router = APIRouter(prefix="/table-session", tags=["table-session"])

OPEN = "open"
APPROVED = "approved"


# --- helpers ---------------------------------------------------------------
def _now():
    return auth.now_iso()


def _profile(user):
    email = (user.get("email") or "").lower()
    return db.query_one(
        "SELECT id, email, full_name, phone FROM customers WHERE email = ?", (email,))


def _require_profile(user):
    prof = _profile(user)
    if not prof or not prof.get("full_name"):
        raise HTTPException(status_code=428, detail="Complete your profile first")
    return prof


def _table_by_token(token: str):
    row = db.query_one(
        "SELECT id, name FROM tables WHERE token = ? AND active = TRUE", (token,))
    if not row:
        raise HTTPException(status_code=404, detail="This table code is not valid")
    return row


def _open_session(table_id: int):
    row = db.query_one(
        "SELECT * FROM table_sessions WHERE table_id = ? AND status = 'open' "
        "ORDER BY id DESC LIMIT 1",
        (table_id,),
    )
    if row:
        return row
    now = _now()
    sid = db.execute_returning_id(
        "INSERT INTO table_sessions (hotel_id, table_id, host_customer_id, status, created_at, opened_at) "
        "VALUES (?, ?, NULL, 'open', ?, ?)",
        (settings.DEFAULT_HOTEL_ID, table_id, now, now),
    )
    return db.query_one("SELECT * FROM table_sessions WHERE id = ?", (sid,))


def _member(session_id: int, customer_id: int):
    return db.query_one(
        "SELECT * FROM table_session_members WHERE session_id = ? AND customer_id = ?",
        (session_id, customer_id),
    )


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _customer_info(customer_id: int):
    return db.query_one(
        "SELECT c.full_name, c.phone FROM customers c JOIN users u ON u.email = c.email "
        "WHERE u.id = ?",
        (_as_int(customer_id),),
    )


def _subtotal(session_id: int, customer_id: int) -> int:
    row = db.query_one(
        "SELECT COALESCE(SUM(oi.price_kes * oi.qty), 0) AS total "
        "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
        "WHERE o.session_id = ? AND o.user_id = ? AND o.status != 'cancelled'",
        (session_id, customer_id),
    )
    return int(row["total"] or 0)


def _require_approved_member(user):
    """Return (session, member) for the user's open session, or raise."""
    session = db.query_one(
        "SELECT * FROM table_sessions s JOIN table_session_members m ON m.session_id = s.id "
        "WHERE m.customer_id = ? AND m.status = 'approved' AND s.status = 'open' "
        "ORDER BY s.id DESC LIMIT 1",
        (user["id"],),
    )
    if not session:
        raise HTTPException(status_code=403, detail="You are not an approved member of a table")
    member = _member(session["id"], user["id"])
    return session, member


# --- join / open -----------------------------------------------------------
class JoinIn(BaseModel):
    table_token: str


@router.post("/join")
def join(body: JoinIn, user=Depends(auth.require_roles("customer"))):
    _require_profile(user)
    table = _table_by_token(body.table_token)
    session = _open_session(table["id"])
    existing = _member(session["id"], user["id"])
    if existing:
        host = _customer_info(session["host_customer_id"]) if session["host_customer_id"] else None
        return {
            "session_id": session["id"],
            "role": existing["role"],
            "status": existing["status"],
            "host_name": (host or {}).get("full_name"),
        }

    # First member of a hostless session becomes the host.
    any_member = db.query_one(
        "SELECT id FROM table_session_members WHERE session_id = ? LIMIT 1", (session["id"],))
    if not session["host_customer_id"] and not any_member:
        db.execute("UPDATE table_sessions SET host_customer_id = ? WHERE id = ?",
                   (user["id"], session["id"]))
        db.execute(
            "INSERT INTO table_session_members (session_id, customer_id, role, status, paid_by_customer_id, joined_at) "
            "VALUES (?, ?, 'host', 'approved', ?, ?)",
            (session["id"], user["id"], user["id"], _now()),
        )
        return {"session_id": session["id"], "role": "host", "status": "approved", "host_name": None}

    # Otherwise join as a pending guest.
    db.execute(
        "INSERT INTO table_session_members (session_id, customer_id, role, status, joined_at) "
        "VALUES (?, ?, 'guest', 'pending', ?)",
        (session["id"], user["id"], _now()),
    )
    host = _customer_info(session["host_customer_id"]) if session["host_customer_id"] else None
    return {
        "session_id": session["id"],
        "role": "guest",
        "status": "pending",
        "host_name": (host or {}).get("full_name"),
    }


# --- state -----------------------------------------------------------------
@router.get("/state")
def state(token: str, user=Depends(auth.require_roles("customer"))):
    table = _table_by_token(token)
    session = db.query_one(
        "SELECT * FROM table_sessions WHERE table_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
        (table["id"],),
    )
    if not session:
        return {"session": None, "members": [], "pending": [], "messages": [], "is_host": False}

    rows = db.query_all(
        "SELECT m.id AS member_id, m.customer_id, m.role, m.status, m.paid_by_customer_id, "
        "c.full_name, c.phone FROM table_session_members m "
        "JOIN users u ON u.id = m.customer_id "
        "LEFT JOIN customers c ON c.email = u.email "
        "WHERE m.session_id = ? ORDER BY m.id",
        (session["id"],),
    )
    members, pending = [], []
    for r in rows:
        if r["status"] == "pending":
            pending.append({"member_id": r["member_id"], "customer_id": r["customer_id"],
                            "full_name": r["full_name"]})
            continue
        if r["status"] != APPROVED:
            continue
        paid_by = r["paid_by_customer_id"] or r["customer_id"]
        members.append({
            "customer_id": r["customer_id"],
            "full_name": r["full_name"],
            "phone": r["phone"],
            "subtotal": _subtotal(session["id"], r["customer_id"]),
            "paid_by_customer_id": paid_by,
            "is_me": r["customer_id"] == user["id"],
        })

    messages = db.query_all(
        "SELECT tm.id, tm.customer_id, tm.message, tm.created_at, c.full_name "
        "FROM table_messages tm JOIN users u ON u.id = tm.customer_id "
        "LEFT JOIN customers c ON c.email = u.email "
        "WHERE tm.session_id = ? ORDER BY tm.id DESC LIMIT 50",
        (session["id"],),
    )
    return {
        "session": {"id": session["id"], "table_id": session["table_id"],
                    "host_customer_id": session["host_customer_id"]},
        "members": members,
        "pending": pending,
        "messages": messages,
        "is_host": _as_int(session["host_customer_id"]) == user["id"],
    }


# --- host approve/decline --------------------------------------------------
class ApproveIn(BaseModel):
    member_id: int
    approve: bool = True


@router.post("/approve")
def approve(body: ApproveIn, user=Depends(auth.require_roles("customer"))):
    target = db.query_one("SELECT * FROM table_session_members WHERE id = ?", (body.member_id,))
    if not target:
        raise HTTPException(status_code=404, detail="Join request not found")
    session = db.query_one("SELECT * FROM table_sessions WHERE id = ?", (target["session_id"],))
    if not session or _as_int(session["host_customer_id"]) != user["id"]:
        raise HTTPException(status_code=403, detail="Only the host can approve")
    if body.approve:
        db.execute(
            "UPDATE table_session_members SET status = 'approved', "
            "paid_by_customer_id = COALESCE(paid_by_customer_id, customer_id) WHERE id = ?",
            (body.member_id,),
        )
    else:
        db.execute("UPDATE table_session_members SET status = 'declined' WHERE id = ?",
                   (body.member_id,))
    return {"ok": True}


# --- pay for another member ------------------------------------------------
class PayForIn(BaseModel):
    target_customer_id: int


@router.post("/pay-for")
def pay_for(body: PayForIn, user=Depends(auth.require_roles("customer"))):
    session, me = _require_approved_member(user)
    if body.target_customer_id == user["id"]:
        raise HTTPException(status_code=400, detail="You already pay for yourself")
    target = db.query_one(
        "SELECT * FROM table_session_members WHERE session_id = ? AND customer_id = ? AND status = 'approved'",
        (session["id"], body.target_customer_id),
    )
    if not target:
        raise HTTPException(status_code=404, detail="Member not at this table")
    # Toggle: if I was covering them, reset to themselves; else I cover them.
    if target["paid_by_customer_id"] == user["id"]:
        db.execute("UPDATE table_session_members SET paid_by_customer_id = ? WHERE id = ?",
                   (target["customer_id"], target["id"]))
        covering = False
    else:
        db.execute("UPDATE table_session_members SET paid_by_customer_id = ? WHERE id = ?",
                   (user["id"], target["id"]))
        covering = True
    return {"ok": True, "covering": covering}


# --- checkout / settle -----------------------------------------------------
class CheckoutIn(BaseModel):
    scope: str = "mine"  # 'mine' | 'table'


@router.post("/checkout")
def checkout(body: CheckoutIn, user=Depends(auth.require_roles("customer"))):
    session, me = _require_approved_member(user)
    if body.scope == "table":
        orders = db.query_all(
            "SELECT id FROM orders WHERE session_id = ? AND status != 'paid' AND status != 'cancelled'",
            (session["id"],),
        )
    else:
        # My orders + orders of members whose paid_by is me.
        orders = db.query_all(
            "SELECT o.id FROM orders o "
            "WHERE o.session_id = ? AND o.status != 'paid' AND o.status != 'cancelled' "
            "AND (o.user_id = ? OR o.user_id IN "
            "  (SELECT customer_id FROM table_session_members WHERE session_id = ? AND paid_by_customer_id = ?))",
            (session["id"], user["id"], session["id"], user["id"]),
        )
    ids = [o["id"] for o in orders]
    for oid in ids:
        db.execute("UPDATE orders SET status = 'paid' WHERE id = ?", (oid,))

    # Close the session once every order at the table is paid.
    unpaid = db.query_one(
        "SELECT COUNT(*) AS n FROM orders WHERE session_id = ? AND status != 'paid' AND status != 'cancelled'",
        (session["id"],),
    )
    closed = False
    if unpaid and unpaid["n"] == 0:
        db.execute("UPDATE table_sessions SET status = 'closed', closed_at = ? WHERE id = ?",
                   (_now(), session["id"]))
        closed = True
    return {"ok": True, "paid_order_ids": ids, "session_closed": closed}


# --- chat ------------------------------------------------------------------
class ChatIn(BaseModel):
    message: str


@router.post("/chat")
def chat(body: ChatIn, user=Depends(auth.require_roles("customer"))):
    session, _ = _require_approved_member(user)
    text = body.message.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Message is empty")
    if len(text) > 500:
        raise HTTPException(status_code=400, detail="Message too long")
    db.execute(
        "INSERT INTO table_messages (session_id, customer_id, message, created_at) "
        "VALUES (?, ?, ?, ?)",
        (session["id"], user["id"], text, _now()),
    )
    return {"ok": True}