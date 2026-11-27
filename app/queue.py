"""Core queue and waiter-assignment rules (the heart of Phase 1).

All timestamps are ISO-8601 UTC text, so plain string comparison sorts them
correctly (same offset). The server is the source of truth for the queue order
and permissions - the phone never decides these.

Definitions:
- A table is WAITING when its open table_session has at least one order and no
  active (ended_at IS NULL) assignment.
- WAITING tables are shown strictly FIFO by the time the FIRST order in the
  session was placed.
- One waiter per table, one table per waiter: a waiter is 'free' until assigned,
  then 'busy' until they press "I'm available" (finish_table).
- Later orders from the SAME table reuse the same waiter automatically, because
  the order joins the same open session that the active assignment points to.
"""
from datetime import datetime, timezone

from . import db
from .config import settings


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_order_at(session_id: int):
    row = db.query_one(
        "SELECT MIN(created_at) AS t FROM orders WHERE session_id = ?", (session_id,)
    )
    return row["t"] if row else None


def get_waiting_tables():
    """Return waiting tables oldest-first (FIFO) with a waiting time in seconds."""
    sessions = db.query_all(
        "SELECT s.id AS session_id, s.table_id, t.name AS table_name "
        "FROM table_sessions s JOIN tables t ON t.id = s.table_id "
        "WHERE s.status = 'open' AND t.active = TRUE AND t.hotel_id = ?",
        (settings.DEFAULT_HOTEL_ID,),
    )
    waiting = []
    now = datetime.now(timezone.utc)
    for s in sessions:
        # Must have at least one order...
        first = _first_order_at(s["session_id"])
        if not first:
            continue
        # ...and no active assignment already.
        active = get_active_assignment(s["table_id"])
        if active:
            continue
        try:
            secs = int((now - datetime.fromisoformat(first)).total_seconds())
        except Exception:
            secs = 0
        waiting.append({
            "table_id": s["table_id"],
            "table_name": s["table_name"],
            "session_id": s["session_id"],
            "first_order_at": first,
            "waiting_seconds": secs,
        })
    waiting.sort(key=lambda w: w["first_order_at"])  # oldest first
    return waiting


def get_active_assignment(table_id: int):
    return db.query_one(
        "SELECT * FROM assignments WHERE table_id = ? AND ended_at IS NULL "
        "ORDER BY id DESC LIMIT 1",
        (table_id,),
    )


def free_waiters():
    return db.query_all(
        "SELECT w.id, w.user_id, u.name, w.status FROM waiters w "
        "JOIN users u ON u.id = w.user_id "
        "WHERE w.hotel_id = ? AND w.status = 'free' ORDER BY w.id",
        (settings.DEFAULT_HOTEL_ID,),
    )


def _waiter_is_free(waiter_id: int) -> bool:
    w = db.query_one("SELECT status FROM waiters WHERE id = ?", (waiter_id,))
    if not w or w["status"] != "free":
        return False
    active = db.query_one(
        "SELECT id FROM assignments WHERE waiter_id = ? AND ended_at IS NULL", (waiter_id,)
    )
    return active is None


def assign_table(table_id: int, waiter_id: int, admin_id: int, reason: str | None = None) -> int:
    """Assign a waiting table to a free waiter. Enforces all Phase 1 rules.

    Raises ValueError with a friendly message if a rule is broken.
    Returns the new assignment id.
    """
    # Rule: the waiter must be free (one table per waiter).
    if not _waiter_is_free(waiter_id):
        raise ValueError("That waiter is not free.")

    # Rule: the table must be waiting (open session, has orders, no assignment).
    if get_active_assignment(table_id):
        raise ValueError("That table already has a waiter.")
    session = db.query_one(
        "SELECT id FROM table_sessions WHERE table_id = ? AND status = 'open' "
        "ORDER BY id DESC LIMIT 1",
        (table_id,),
    )
    if not session or not _first_order_at(session["id"]):
        raise ValueError("That table has no waiting order.")

    # Rule: FIFO. Assigning anyone but the oldest waiting table needs a reason.
    waiting = get_waiting_tables()
    is_oldest = bool(waiting) and waiting[0]["table_id"] == table_id
    if not is_oldest:
        if not reason or not reason.strip():
            raise ValueError("Out-of-order assignment needs a reason.")
        db.execute(
            "INSERT INTO audit_log (hotel_id, actor_id, action, detail, created_at) "
            "VALUES (?, ?, 'out_of_order_assign', ?, ?)",
            (settings.DEFAULT_HOTEL_ID, admin_id, f"table {table_id} -> waiter {waiter_id}: {reason}", _now()),
        )

    # Do the assignment.
    assignment_id = db.execute_returning_id(
        "INSERT INTO assignments (hotel_id, table_id, session_id, waiter_id, assigned_by, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (settings.DEFAULT_HOTEL_ID, table_id, session["id"], waiter_id, admin_id, reason, _now()),
    )
    db.execute("UPDATE waiters SET status = 'busy' WHERE id = ?", (waiter_id,))
    db.execute("UPDATE tables SET status = 'being_served' WHERE id = ?", (table_id,))
    # Orders in this session move from 'placed' to 'accepted'.
    db.execute("UPDATE orders SET status = 'accepted' WHERE session_id = ? AND status = 'placed'",
               (session["id"],))
    return assignment_id


def reassign_table(table_id: int, new_waiter_id: int, admin_id: int, reason: str) -> int:
    """Move a table from its current waiter to a new free waiter (always logged)."""
    if not reason or not reason.strip():
        raise ValueError("Reassignment needs a reason.")
    active = get_active_assignment(table_id)
    if not active:
        raise ValueError("That table has no waiter to reassign from.")
    if not _waiter_is_free(new_waiter_id):
        raise ValueError("The new waiter is not free.")
    old_waiter = active["waiter_id"]
    now = _now()
    # End the old assignment and free the old waiter.
    db.execute("UPDATE assignments SET ended_at = ? WHERE id = ?", (now, active["id"]))
    db.execute("UPDATE waiters SET status = 'free', last_active_at = ? WHERE id = ?",
               (now, old_waiter))
    # Create the new assignment (keep the same session so same-table routing holds).
    new_id = db.execute_returning_id(
        "INSERT INTO assignments (hotel_id, table_id, session_id, waiter_id, assigned_by, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (settings.DEFAULT_HOTEL_ID, table_id, active["session_id"], new_waiter_id, admin_id, reason, now),
    )
    db.execute("UPDATE waiters SET status = 'busy' WHERE id = ?", (new_waiter_id,))
    db.execute(
        "INSERT INTO audit_log (hotel_id, actor_id, action, detail, created_at) "
        "VALUES (?, ?, 'reassign', ?, ?)",
        (settings.DEFAULT_HOTEL_ID, admin_id,
         f"table {table_id}: waiter {old_waiter} -> {new_waiter_id}: {reason}", now),
    )
    return new_id


def finish_table(table_id: int, waiter_id: int):
    """Waiter presses 'I'm available': close the table, free the waiter."""
    active = get_active_assignment(table_id)
    if not active:
        raise ValueError("That table has no active waiter.")
    if active["waiter_id"] != waiter_id:
        raise ValueError("Only the assigned waiter can finish this table.")
    db.execute("UPDATE assignments SET ended_at = ? WHERE id = ?", (_now(), active["id"]))
    db.execute("UPDATE waiters SET status = 'free', last_active_at = ? WHERE id = ?",
               (_now(), waiter_id))
    db.execute("UPDATE tables SET status = 'free' WHERE id = ?", (table_id,))
    if active["session_id"]:
        db.execute("UPDATE table_sessions SET status = 'closed', closed_at = ? WHERE id = ?",
                   (_now(), active["session_id"]))
        db.execute("UPDATE orders SET status = 'served' WHERE session_id = ?", (active["session_id"],))
    return True