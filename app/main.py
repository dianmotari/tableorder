"""TableOrder - FastAPI application entry point.

Phase 1, Step 1: just the app skeleton and a /health check that also tests the
database connection. Routers for admin/customer/waiter are added in later steps.
"""
from contextlib import asynccontextmanager

# Load .env first so settings below pick up local values without --env-file.
try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from . import auth, db, schema
from .config import settings
from .routers import admin, customer, menu, orders, tables, waiter


def _bootstrap_admin():
    """Create the first admin from env vars if there is no admin yet."""
    if not settings.ADMIN_EMAIL or not settings.ADMIN_PASSWORD:
        return
    existing = db.query_one("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    if existing:
        return
    db.execute(
        "INSERT INTO users (hotel_id, role, email, name, password_hash, active, created_at) "
        "VALUES (?, 'admin', ?, ?, ?, TRUE, ?)",
        (
            settings.DEFAULT_HOTEL_ID,
            settings.ADMIN_EMAIL.lower(),
            "Admin",
            auth.hash_password(settings.ADMIN_PASSWORD),
            auth.now_iso(),
        ),
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build all Phase 1 tables, ensure the default hotel, then the first admin.
    schema.create_all()
    _bootstrap_admin()
    yield


app = FastAPI(title="TableOrder", lifespan=lifespan)

# Trust X-Forwarded-Proto/For from the cloud reverse proxy so HTTPS redirect and
# secure cookies (COOKIE_SECURE=1) work correctly behind Render/Railway/etc.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")

app.include_router(admin.router)
app.include_router(tables.router)
app.include_router(menu.router)
app.include_router(customer.router)
app.include_router(orders.router)
app.include_router(waiter.router)

# Serve uploaded menu photos (and future static assets) at /static.
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/health")
def health():
    """Simple check that the server AND the database are reachable."""
    try:
        row = db.query_one("SELECT 1 AS ok")
        db_ok = bool(row and row.get("ok") == 1)
    except Exception as exc:  # show the last line of any error to the user
        return {"status": "error", "database": str(exc).splitlines()[-1]}
    return {"status": "ok" if db_ok else "error", "database": "ok" if db_ok else "fail"}


@app.get("/")
def index():
    return {"message": "TableOrder API is running. See /health and /docs."}