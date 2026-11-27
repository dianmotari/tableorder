"""Shared test setup: give every test a clean database.

The local SQLite file persists between runs, so without this, waiting tables and
orders from one test leak into the next and break FIFO/queue assertions. Before
each test we delete all rows (keeping the default hotel row that schema seeds).
"""
import pytest

from app import db, schema

# Tables to empty before each test (children first is not required without FKs
# enforced across the board, but we keep a safe order anyway).
_WIPE = [
    "order_items",
    "orders",
    "assignments",
    "table_sessions",
    "waiters",
    "otp_codes",
    "sessions",
    "audit_log",
    "menu_items",
    "categories",
    "tables",
    "users",
]


@pytest.fixture(autouse=True)
def clean_db():
    schema.create_all()
    with db.get_conn() as conn:
        cur = conn.cursor()
        for table in _WIPE:
            cur.execute(f"DELETE FROM {table}")
    yield