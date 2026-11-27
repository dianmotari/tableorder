"""Database schema for Phase 1.

Creates all tables if they do not exist. Works on SQLite (local) and PostgreSQL
(when DATABASE_URL is set). We keep two simple dialects because their column
types differ a little. Call create_all() once at startup.

Rules baked in here:
- hotel_id is on tables/menu/users from day one (multi-hotel later).
- tables have an unguessable token and a soft-delete flag (active = 0).
- sessions store only a token HASH, never the raw token.
- timestamps are stored as ISO-8601 UTC text so both databases behave the same.
"""
from . import db

# --- SQLite dialect ---------------------------------------------------------
_SQLITE = [
    """CREATE TABLE IF NOT EXISTS hotels (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        logo_url TEXT,
        wifi_name TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id INTEGER NOT NULL,
        role TEXT NOT NULL,               -- 'admin' | 'waiter' | 'customer'
        email TEXT,
        google_sub TEXT,
        name TEXT,
        password_hash TEXT,               -- staff only (bcrypt)
        active INTEGER NOT NULL DEFAULT 1,
        must_change_password INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS tables (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id INTEGER NOT NULL,
        name TEXT NOT NULL,               -- e.g. "Table 7"
        seats INTEGER,
        area TEXT,                        -- e.g. "Garden"
        token TEXT NOT NULL UNIQUE,       -- unguessable, in the QR link
        status TEXT NOT NULL DEFAULT 'free',
        active INTEGER NOT NULL DEFAULT 1,-- soft-delete: 0 kills the QR
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL UNIQUE,
        full_name TEXT,
        phone TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS table_sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id INTEGER,
        table_id INTEGER NOT NULL,
        host_customer_id INTEGER,
        status TEXT NOT NULL DEFAULT 'open', -- 'open' | 'closed'
        created_at TEXT,
        opened_at TEXT,
        closed_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS table_session_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        role TEXT NOT NULL DEFAULT 'guest',      -- 'host' | 'guest'
        status TEXT NOT NULL DEFAULT 'pending',  -- 'approved' | 'pending' | 'declined'
        paid_by_customer_id INTEGER,
        joined_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS table_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS menu_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id INTEGER NOT NULL,
        category_id INTEGER,
        name TEXT NOT NULL,
        description TEXT,
        price_kes INTEGER NOT NULL,       -- whole shillings
        photo_url TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id INTEGER NOT NULL,
        table_id INTEGER NOT NULL,
        session_id INTEGER,
        user_id INTEGER,                  -- the customer who placed it
        guest_label TEXT,                 -- 'Guest 1', seat, or name
        status TEXT NOT NULL DEFAULT 'placed',
        note TEXT,
        idempotency_key TEXT UNIQUE,      -- stops double-submit
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        menu_item_id INTEGER,
        name_snapshot TEXT NOT NULL,      -- name at order time
        price_kes INTEGER NOT NULL,       -- price at order time (server truth)
        qty INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'placed'
    )""",
    """CREATE TABLE IF NOT EXISTS waiters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'free', -- free|busy|on_break|off_duty
        last_active_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS assignments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id INTEGER NOT NULL,
        table_id INTEGER NOT NULL,
        session_id INTEGER,
        waiter_id INTEGER NOT NULL,
        assigned_by INTEGER,              -- admin user id
        reason TEXT,                      -- required if out of FIFO order
        created_at TEXT NOT NULL,
        ended_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,  -- never store the raw token
        created_at TEXT NOT NULL,
        expires_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS otp_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        code_hash TEXT NOT NULL,          -- store hashed, not the digits
        attempts INTEGER NOT NULL DEFAULT 0,
        consumed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hotel_id INTEGER NOT NULL,
        actor_id INTEGER,                 -- who did it
        action TEXT NOT NULL,             -- e.g. 'reassign'
        detail TEXT,
        created_at TEXT NOT NULL
    )""",
]

# --- PostgreSQL dialect (same tables, different types) ----------------------
_PG = [
    """CREATE TABLE IF NOT EXISTS hotels (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        logo_url TEXT,
        wifi_name TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        hotel_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        email TEXT,
        google_sub TEXT,
        name TEXT,
        password_hash TEXT,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS tables (
        id SERIAL PRIMARY KEY,
        hotel_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        seats INTEGER,
        area TEXT,
        token TEXT NOT NULL UNIQUE,
        status TEXT NOT NULL DEFAULT 'free',
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS customers (
        id SERIAL PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        full_name TEXT,
        phone TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS table_sessions (
        id SERIAL PRIMARY KEY,
        hotel_id INTEGER,
        table_id INTEGER NOT NULL,
        host_customer_id INTEGER,
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT,
        opened_at TEXT,
        closed_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS table_session_members (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        role TEXT NOT NULL DEFAULT 'guest',
        status TEXT NOT NULL DEFAULT 'pending',
        paid_by_customer_id INTEGER,
        joined_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS table_messages (
        id SERIAL PRIMARY KEY,
        session_id INTEGER NOT NULL,
        customer_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY,
        hotel_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS menu_items (
        id SERIAL PRIMARY KEY,
        hotel_id INTEGER NOT NULL,
        category_id INTEGER,
        name TEXT NOT NULL,
        description TEXT,
        price_kes INTEGER NOT NULL,
        photo_url TEXT,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        hotel_id INTEGER NOT NULL,
        table_id INTEGER NOT NULL,
        session_id INTEGER,
        user_id INTEGER,
        guest_label TEXT,
        status TEXT NOT NULL DEFAULT 'placed',
        note TEXT,
        idempotency_key TEXT UNIQUE,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS order_items (
        id SERIAL PRIMARY KEY,
        order_id INTEGER NOT NULL,
        menu_item_id INTEGER,
        name_snapshot TEXT NOT NULL,
        price_kes INTEGER NOT NULL,
        qty INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'placed'
    )""",
    """CREATE TABLE IF NOT EXISTS waiters (
        id SERIAL PRIMARY KEY,
        hotel_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'free',
        last_active_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS assignments (
        id SERIAL PRIMARY KEY,
        hotel_id INTEGER NOT NULL,
        table_id INTEGER NOT NULL,
        session_id INTEGER,
        waiter_id INTEGER NOT NULL,
        assigned_by INTEGER,
        reason TEXT,
        created_at TEXT NOT NULL,
        ended_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        created_at TEXT NOT NULL,
        expires_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS otp_codes (
        id SERIAL PRIMARY KEY,
        email TEXT NOT NULL,
        code_hash TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        consumed INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS audit_log (
        id SERIAL PRIMARY KEY,
        hotel_id INTEGER NOT NULL,
        actor_id INTEGER,
        action TEXT NOT NULL,
        detail TEXT,
        created_at TEXT NOT NULL
    )""",
]


def _column_exists(table: str, column: str) -> bool:
    if db._is_postgres():
        row = db.query_one(
            "SELECT 1 AS ok FROM information_schema.columns "
            "WHERE table_name = ? AND column_name = ?",
            (table, column),
        )
        return bool(row)
    rows = db.query_all(f"PRAGMA table_info({table})")
    return any(r["name"] == column for r in rows)


def _migrate():
    """Small, safe migrations for columns added after the first release.

    create_all() only CREATEs missing tables; it never alters existing ones, so
    new columns are added here with ADD COLUMN (a no-op if already present).
    """
    if not _column_exists("users", "must_change_password"):
        default = "TRUE" if db._is_postgres() else "1"
        with db.get_conn() as conn:
            conn.cursor().execute(
                db._translate(
                    "ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT "
                    + default
                )
            )
    # table_sessions gained host_customer_id and created_at for the table-session
    # system. Add them to existing databases (no-op if already present).
    for column in ("host_customer_id", "created_at"):
        if not _column_exists("table_sessions", column):
            with db.get_conn() as conn:
                conn.cursor().execute(
                    db._translate(f"ALTER TABLE table_sessions ADD COLUMN {column} TEXT")
                )


def create_all():
    """Create every Phase 1 table if it is missing, then ensure a default hotel."""
    statements = _PG if db._is_postgres() else _SQLITE
    with db.get_conn() as conn:
        cur = conn.cursor()
        for stmt in statements:
            cur.execute(db._translate(stmt))
    _migrate()
    # Make sure a default hotel exists so hotel_id references always resolve.
    existing = db.query_one("SELECT id FROM hotels WHERE id = ?", (1,))
    if not existing:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            "INSERT INTO hotels (id, name, created_at) VALUES (?, ?, ?)",
            (1, "My Hotel", now),
        )