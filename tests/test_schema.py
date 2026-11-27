"""Step 2 test: every Phase 1 table is created and the default hotel exists.

Run from the project root:  python -m pytest -q
"""
from app import db, schema

# The full list of tables Phase 1 needs.
EXPECTED = {
    "hotels",
    "users",
    "tables",
    "table_sessions",
    "categories",
    "menu_items",
    "orders",
    "order_items",
    "waiters",
    "assignments",
    "sessions",
    "otp_codes",
    "audit_log",
}


def _table_names():
    if db._is_postgres():
        rows = db.query_all(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public'"
        )
        return {r["table_name"] for r in rows}
    rows = db.query_all("SELECT name FROM sqlite_master WHERE type = 'table'")
    return {r["name"] for r in rows}


def test_all_tables_created():
    schema.create_all()
    names = _table_names()
    missing = EXPECTED - names
    assert not missing, f"missing tables: {missing}"


def test_default_hotel_exists():
    schema.create_all()
    hotel = db.query_one("SELECT id, name FROM hotels WHERE id = ?", (1,))
    assert hotel is not None
    assert hotel["id"] == 1