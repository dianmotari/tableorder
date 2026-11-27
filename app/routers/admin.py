"""Admin routes: login, logout, current-user, and a protected demo endpoint.

Only users with role 'admin' may use these (enforced by require_roles).
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
import secrets

from .. import auth, db, queue
from ..config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/login")
def login(body: LoginIn, response: Response):
    # Server is the source of truth: check the password here, never trust the phone.
    user = db.query_one(
        "SELECT id, email, password_hash, role, active FROM users "
        "WHERE email = ? AND role = 'admin'",
        (str(body.email).lower(),),
    )
    if not user or not user.get("active") or not auth.verify_password(
        body.password, user["password_hash"]
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong email or password"
        )
    token = auth.create_session(user["id"])
    response.set_cookie(
        auth.COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        max_age=30 * 24 * 3600,
    )
    return {"ok": True, "email": user["email"]}


@router.post("/logout")
def logout(response: Response):
    # (Token is cleared client-side; server rows expire on their own.)
    response.delete_cookie(auth.COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
def me(user=Depends(auth.require_roles("admin"))):
    return {"id": user["id"], "email": user["email"], "role": user["role"]}


@router.get("/ping")
def ping(user=Depends(auth.require_roles("admin"))):
    """A protected endpoint used to prove the role check works."""
    return {"message": "admin only", "role": user["role"]}


# --- waiters (admin creates staff accounts; no public staff sign-up) -------
class WaiterIn(BaseModel):
    name: str
    email: str
    password: str | None = None  # ignored: admin never types a password


def _temp_password(n: int = 8) -> str:
    # URL-safe random, no confusing characters, exactly n chars.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


@router.get("/waiters")
def list_waiters(user=Depends(auth.require_roles("admin"))):
    rows = db.query_all(
        "SELECT w.id, w.user_id, u.name, u.email, w.status FROM waiters w "
        "JOIN users u ON u.id = w.user_id WHERE w.hotel_id = ? ORDER BY w.id",
        (settings.DEFAULT_HOTEL_ID,),
    )
    return rows


@router.post("/waiters", status_code=201)
def add_waiter(body: WaiterIn, user=Depends(auth.require_roles("admin"))):
    email = body.email.lower().strip()
    if db.query_one("SELECT id FROM users WHERE email = ?", (email,)):
        raise HTTPException(status_code=400, detail="Email already used")
    # Auto-generate a temporary password; the admin shows it to the waiter once.
    temp = _temp_password()
    uid = db.execute_returning_id(
        "INSERT INTO users "
        "(hotel_id, role, email, name, password_hash, active, must_change_password, created_at) "
        "VALUES (?, 'waiter', ?, ?, ?, TRUE, TRUE, ?)",
        (settings.DEFAULT_HOTEL_ID, email, body.name, auth.hash_password(temp), auth.now_iso()),
    )
    wid = db.execute_returning_id(
        "INSERT INTO waiters (hotel_id, user_id, status) VALUES (?, ?, 'free')",
        (settings.DEFAULT_HOTEL_ID, uid),
    )
    # temp_password is shown ONLY here, once.
    return {"id": wid, "user_id": uid, "email": email, "temp_password": temp}


class WaiterEdit(BaseModel):
    name: str | None = None
    email: str | None = None
    password: str | None = None
    status: str | None = None  # free|busy|on_break|off_duty


@router.patch("/waiters/{waiter_id}")
def edit_waiter(waiter_id: int, body: WaiterEdit, user=Depends(auth.require_roles("admin"))):
    row = db.query_one("SELECT user_id FROM waiters WHERE id = ?", (waiter_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Waiter not found")
    uid = row["user_id"]
    if body.name is not None:
        db.execute("UPDATE users SET name = ? WHERE id = ?", (body.name, uid))
    if body.email is not None:
        email = body.email.lower().strip()
        if db.query_one("SELECT id FROM users WHERE email = ? AND id != ?", (email, uid)):
            raise HTTPException(status_code=400, detail="Email already used")
        db.execute("UPDATE users SET email = ? WHERE id = ?", (email, uid))
    if body.password:
        # Admin-set password must be changed by the waiter on next login.
        db.execute("UPDATE users SET password_hash = ?, must_change_password = TRUE WHERE id = ?",
                   (auth.hash_password(body.password), uid))
    if body.status is not None:
        db.execute("UPDATE waiters SET status = ? WHERE id = ?", (body.status, waiter_id))
    return {"ok": True}


@router.delete("/waiters/{waiter_id}")
def delete_waiter(waiter_id: int, user=Depends(auth.require_roles("admin"))):
    # Soft-disable: keep history, block login, take them off the floor.
    db.execute("UPDATE users SET active = FALSE WHERE id = (SELECT user_id FROM waiters WHERE id = ?)",
               (waiter_id,))
    db.execute("UPDATE waiters SET status = 'off_duty' WHERE id = ?", (waiter_id,))
    db.execute(
        "INSERT INTO audit_log (hotel_id, actor_id, action, detail, created_at) "
        "VALUES (?, ?, 'delete_waiter', ?, ?)",
        (settings.DEFAULT_HOTEL_ID, user["id"], str(waiter_id), auth.now_iso()),
    )
    return {"ok": True}


# --- live board (polled every 3-5s by the admin page) ---------------------
@router.get("/board")
def board(user=Depends(auth.require_roles("admin"))):
    """Everything the admin screen needs in one call: waiting queue (FIFO),
    free waiters, busy waiters, and table statuses."""
    waiting = queue.get_waiting_tables()
    for w in waiting:
        w["items"] = db.query_all(
            "SELECT oi.name_snapshot AS name, oi.qty, oi.price_kes "
            "FROM order_items oi JOIN orders o ON o.id = oi.order_id "
            "WHERE o.session_id = ?",
            (w["session_id"],),
        )
    return {
        "waiting": waiting,                     # oldest first
        "free_waiters": queue.free_waiters(),
        "waiters": db.query_all(
            "SELECT w.id, u.name, w.status FROM waiters w JOIN users u ON u.id = w.user_id "
            "WHERE w.hotel_id = ? ORDER BY w.id",
            (settings.DEFAULT_HOTEL_ID,),
        ),
        "tables": db.query_all(
            "SELECT id, name, status FROM tables WHERE hotel_id = ? AND active = TRUE ORDER BY id",
            (settings.DEFAULT_HOTEL_ID,),
        ),
    }


class AssignIn(BaseModel):
    table_id: int
    waiter_id: int
    reason: str | None = None


@router.post("/assign")
def assign(body: AssignIn, user=Depends(auth.require_roles("admin"))):
    try:
        aid = queue.assign_table(body.table_id, body.waiter_id, user["id"], body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "assignment_id": aid}


@router.post("/reassign")
def reassign(body: AssignIn, user=Depends(auth.require_roles("admin"))):
    try:
        aid = queue.reassign_table(body.table_id, body.waiter_id, user["id"], body.reason or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "assignment_id": aid}


@router.get("/audit")
def audit(user=Depends(auth.require_roles("admin"))):
    return db.query_all(
        "SELECT id, actor_id, action, detail, created_at FROM audit_log "
        "WHERE hotel_id = ? ORDER BY id DESC LIMIT 100",
        (settings.DEFAULT_HOTEL_ID,),
    )