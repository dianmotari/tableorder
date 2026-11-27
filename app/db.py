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
    """Yield a DB connection. Commits on success, rolls back on any error."""
    if _is_postgres():
        conn = _pg_connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
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


def _pg_connect():
    global _pg_pool
    if _pg_pool is None:
        # Imported lazily so local dev does not need psycopg installed.
        from psycopg_pool import ConnectionPool

        # check=... is the pool "pre-ping": it validates a connection before
        # handing it out, so dropped cloud DB connections are recycled (this is
        # the psycopg equivalent of SQLAlchemy's pool_pre_ping=True).
        _pg_pool = ConnectionPool(
            _pg_dsn(),
            min_size=1,
            max_size=5,
            check=ConnectionPool.check_connection,
        )
    return _pg_pool.getconn()


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