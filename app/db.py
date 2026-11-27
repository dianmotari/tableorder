"""Database layer: works with SQLite locally and PostgreSQL when DATABASE_URL is set.

We use plain SQL (parameterised only) so there is no heavy ORM to learn.
Call get_conn() to get a connection; it commits on success and rolls back on error.

To keep our SQL the same for both databases we always write "?" placeholders.
For PostgreSQL we translate "?" to "%s" automatically in _run().
"""
import sqlite3
from contextlib import contextmanager

from .config import settings

# Created lazily so importing this module never touches the disk.
_pg_pool = None


def _is_postgres() -> bool:
    return settings.DATABASE_URL.startswith("postgres")


def _sqlite_path() -> str:
    # Allow "sqlite:///file.db" style too, but default to a local file.
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return "tableorder.db"


@contextmanager
def get_conn():
    """Yield a DB connection. Commits on success, rolls back on any error.

    Every connection is returned to the pool in a finally block (Postgres) or
    closed (SQLite), so nothing is leaked even when the body raises.
    """
    if _is_postgres():
        pool = _ensure_pool()
        # The pool's connection() context manager guarantees the connection is
        # returned to the pool on exit (this is what prevents PoolTimeout).
        with pool.connection() as conn:
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    else:
        conn = sqlite3.connect(_sqlite_path())
        conn.row_factory = sqlite3.Row  # rows behave like dicts
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _pg_dsn() -> str:
    """Normalise common hosted-Postgres URL forms to a plain postgresql:// DSN.

    Accepts postgresql://, postgresql+psycopg2://, postgres:// etc. and strips
    the SQLAlchemy-style "+driver" so psycopg can connect.
    """
    url = settings.DATABASE_URL
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if "+psycopg2" in url:
        url = url.replace("+psycopg2", "")
    return url


def ensure_users_email_unique():
    """Deduplicate users by case-insensitive email, then add a unique index.

    Keeps the lowest id in each duplicate group, reassigns that user's sessions,
    orders and waiters to the kept row, and deletes the extras. Safe to run on
    every startup (idempotent) on both SQLite and PostgreSQL.
    """
    rows = query_all("SELECT id, email FROM users WHERE email IS NOT NULL ORDER BY id")
    seen = {}
    duplicates = []
    for r in rows:
        key = (r["email"] or "").strip().lower()
        if not key:
            continue
        if key in seen:
            duplicates.append((seen[key], r["id"]))
        else:
            seen[key] = r["id"]

    with get_conn() as conn:
        cur = conn.cursor()
        for keep_id, dup_id in duplicates:
            for table in ("sessions", "orders", "waiters"):
                cur.execute(_translate(f"UPDATE {table} SET user_id = ? WHERE user_id = ?"),
                            (keep_id, dup_id))
            cur.execute(_translate("DELETE FROM users WHERE id = ?"), (dup_id,))
        # Expression index works on both engines; NULL emails are allowed.
        cur.execute(
            _translate(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email_unique "
                "ON users (LOWER(email))"
            )
        )


def _ensure_pool():
    """Create the global connection pool once and return it (no acquisition)."""
    global _pg_pool
    if _pg_pool is None:
        # Imported lazily so local dev does not need psycopg installed.
        from psycopg_pool import ConnectionPool

        # check=... is the pool "pre-ping": it validates a connection before
        # handing it out, so dropped cloud DB connections are recycled (the
        # psycopg equivalent of SQLAlchemy's pool_pre_ping=True).
        # max_lifetime/max_idle recycle long-lived connections (cloud DBs and
        # pgbouncer drop idle ones). prepare_threshold=None disables prepared
        # statements so transaction-mode poolers (Render/Neon/pgbouncer) work.
        _pg_pool = ConnectionPool(
            _pg_dsn(),
            min_size=1,
            max_size=5,
            max_lifetime=300,
            max_idle=60,
            check=ConnectionPool.check_connection,
            kwargs={"prepare_threshold": None},
        )
    return _pg_pool


def _translate(sql: str) -> str:
    """Turn '?' placeholders into '%s' for PostgreSQL."""
    if _is_postgres():
        return sql.replace("?", "%s")
    return sql


def query_one(sql: str, params=()):
    """Run a SELECT and return the first row (as a dict) or None."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(_translate(sql), params)
        row = cur.fetchone()
        if row is None:
            return None
        if isinstance(row, sqlite3.Row):
            return dict(row)
        # psycopg returns tuples by default; use cursor description for names.
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))


def query_all(sql: str, params=()):
    """Run a SELECT and return all rows as a list of dicts."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(_translate(sql), params)
        rows = cur.fetchall()
        if not rows:
            return []
        if isinstance(rows[0], sqlite3.Row):
            return [dict(r) for r in rows]
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in rows]


def execute(sql: str, params=()):
    """Run an INSERT/UPDATE/DELETE and return lastrowid (SQLite) or rowcount."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(_translate(sql), params)
        last = cur.lastrowid if hasattr(cur, "lastrowid") else None
        return last


def execute_returning_id(sql: str, params=()):
    """For INSERTs where we need the new id on both databases."""
    if _is_postgres():
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(_translate(sql) + " RETURNING id", params)
            row = cur.fetchone()
            return row[0]
    return execute(sql, params)