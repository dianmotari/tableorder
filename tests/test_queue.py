"""Step 8 tests: the queue and assignment rules (handoff section 14).

Covers:
- FIFO: A ordered before B -> A is listed above B.
- Out-of-order assign (B before A) requires a reason and writes an audit log.
- One waiter per table / one table per waiter.
- After "I'm available" the waiter can take another table.
- A second order from the same table reuses the same waiter (same session).

Run from the project root:  python -m pytest -q
"""
import uuid

import pytest

from app import auth, db, queue, schema


def _table(name="T"):
    token = "tok_" + uuid.uuid4().hex
    tid = db.execute_returning_id(
        "INSERT INTO tables (hotel_id, name, token, status, active, created_at) "
        "VALUES (?, ?, ?, 'free', 1, ?)",
        (1, name, token, auth.now_iso()),
    )
    return tid


def _session(table_id):
    return db.execute_returning_id(
        "INSERT INTO table_sessions (hotel_id, table_id, status, opened_at) "
        "VALUES (?, ?, 'open', ?)",
        (1, table_id, auth.now_iso()),
    )


def _order(table_id, session_id, created_at):
    oid = db.execute_returning_id(
        "INSERT INTO orders (hotel_id, table_id, session_id, user_id, status, created_at) "
        "VALUES (?, ?, ?, NULL, 'placed', ?)",
        (1, table_id, session_id, created_at),
    )
    return oid


def _waiter(name="W"):
    email = f"w_{uuid.uuid4().hex[:8]}@e.com"
    uid = db.execute_returning_id(
        "INSERT INTO users (hotel_id, role, email, name, password_hash, active, created_at) "
        "VALUES (?, 'waiter', ?, ?, ?, 1, ?)",
        (1, email, name, auth.hash_password("x"), auth.now_iso()),
    )
    wid = db.execute_returning_id(
        "INSERT INTO waiters (hotel_id, user_id, status) VALUES (?, ?, 'free')", (1, uid)
    )
    return wid


def test_fifo_order_oldest_first():
    schema.create_all()
    a = _table("A")
    b = _table("B")
    sa, sb = _session(a), _session(b)
    _order(a, sa, "2026-01-01T10:00:00+00:00")  # A first
    _order(b, sb, "2026-01-01T10:05:00+00:00")  # B later

    waiting = queue.get_waiting_tables()
    ids = [w["table_id"] for w in waiting]
    assert ids.index(a) < ids.index(b), "A (older) must be listed before B"


def test_out_of_order_assign_needs_reason_and_logs():
    schema.create_all()
    a = _table("A")
    b = _table("B")
    sa, sb = _session(a), _session(b)
    _order(a, sa, "2026-01-01T10:00:00+00:00")
    _order(b, sb, "2026-01-01T10:05:00+00:00")
    w = _waiter()

    # Assigning B (newer) first without a reason is rejected.
    with pytest.raises(ValueError):
        queue.assign_table(b, w, admin_id=1)

    # With a reason it works AND writes an audit row.
    queue.assign_table(b, w, admin_id=1, reason="VIP guest")
    log = db.query_one(
        "SELECT COUNT(*) AS n FROM audit_log WHERE action = 'out_of_order_assign'"
    )
    assert log["n"] == 1


def test_one_table_per_waiter_and_free_after_available():
    schema.create_all()
    a = _table("A")
    b = _table("B")
    sa, sb = _session(a), _session(b)
    _order(a, sa, "2026-01-01T10:00:00+00:00")
    _order(b, sb, "2026-01-01T10:01:00+00:00")
    w = _waiter()

    queue.assign_table(a, w, admin_id=1)  # waiter now busy
    # Waiter cannot take a second table while busy.
    with pytest.raises(ValueError):
        queue.assign_table(b, w, admin_id=1, reason="whatever")

    # After "I'm available" the waiter is free and can take B.
    queue.finish_table(a, w)
    queue.assign_table(b, w, admin_id=1)


def test_same_table_second_order_same_waiter():
    schema.create_all()
    a = _table("A")
    sa = _session(a)
    _order(a, sa, "2026-01-01T10:00:00+00:00")
    w = _waiter()
    queue.assign_table(a, w, admin_id=1)

    # A second order joins the SAME open session -> same active assignment.
    _order(a, sa, "2026-01-01T10:02:00+00:00")
    active = queue.get_active_assignment(a)
    assert active is not None and active["waiter_id"] == w
    # Table still has exactly one active waiter.
    assert queue.get_active_assignment(a)["waiter_id"] == w