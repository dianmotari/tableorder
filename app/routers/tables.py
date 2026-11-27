"""Table management (admin only) + the public /t/<token> landing.

Admin can add, list, edit, soft-delete (disable) and regenerate a table's QR.
Soft-delete keeps history: active = 0 makes the token stop working but the row
and its orders stay. Regenerating replaces the token, so the old printed code
dies immediately.

Printable QR is a styled page (qr-code-styling, error-correction level H) with
"print one" and "print all" views. The QR holds the /t/<token> link.
"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .. import auth, db, qr
from ..config import settings

router = APIRouter(tags=["tables"])


# --- schemas ---------------------------------------------------------------
class TableIn(BaseModel):
    name: str
    seats: int | None = None
    area: str | None = None


class TableOut(BaseModel):
    name: str | None = None
    seats: int | None = None
    area: str | None = None
    status: str | None = None


def _get_table(token: str):
    return db.query_one(
        "SELECT id, hotel_id, name, seats, area, token, status, active "
        "FROM tables WHERE token = ?",
        (token,),
    )


# --- admin: list / add -----------------------------------------------------
@router.get("/admin/tables")
def list_tables(user=Depends(auth.require_roles("admin"))):
    return db.query_all(
        "SELECT id, name, seats, area, token, status, active "
        "FROM tables WHERE hotel_id = ? AND active = TRUE ORDER BY id",
        (settings.DEFAULT_HOTEL_ID,),
    )


@router.post("/admin/tables", status_code=201)
def add_table(body: TableIn, user=Depends(auth.require_roles("admin"))):
    token = qr.new_token()
    new_id = db.execute_returning_id(
        "INSERT INTO tables (hotel_id, name, seats, area, token, status, active, created_at) "
        "VALUES (?, ?, ?, ?, ?, 'free', TRUE, ?)",
        (settings.DEFAULT_HOTEL_ID, body.name, body.seats, body.area, token, auth.now_iso()),
    )
    return {"id": new_id, "token": token, "name": body.name}


# --- admin: edit / disable / regenerate -----------------------------------
@router.patch("/admin/tables/{table_id}")
def edit_table(table_id: int, body: TableOut, user=Depends(auth.require_roles("admin"))):
    row = db.query_one("SELECT id FROM tables WHERE id = ? AND active = TRUE", (table_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Table not found")
    db.execute(
        "UPDATE tables SET name = COALESCE(?, name), seats = ?, area = ?, status = COALESCE(?, status) "
        "WHERE id = ?",
        (body.name, body.seats, body.area, body.status, table_id),
    )
    return {"ok": True}


@router.delete("/admin/tables/{table_id}")
def delete_table(table_id: int, user=Depends(auth.require_roles("admin"))):
    # Soft-delete: keep the row and history, just stop the QR working.
    db.execute("UPDATE tables SET active = FALSE WHERE id = ?", (table_id,))
    db.execute(
        "INSERT INTO audit_log (hotel_id, actor_id, action, detail, created_at) "
        "VALUES (?, ?, 'delete_table', ?, ?)",
        (settings.DEFAULT_HOTEL_ID, user["id"], str(table_id), auth.now_iso()),
    )
    return {"ok": True}


@router.post("/admin/tables/{table_id}/regenerate")
def regenerate(table_id: int, user=Depends(auth.require_roles("admin"))):
    row = db.query_one("SELECT id FROM tables WHERE id = ? AND active = TRUE", (table_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Table not found")
    token = qr.new_token()  # old token dies here
    db.execute("UPDATE tables SET token = ? WHERE id = ?", (token, table_id))
    db.execute(
        "INSERT INTO audit_log (hotel_id, actor_id, action, detail, created_at) "
        "VALUES (?, ?, 'regenerate_token', ?, ?)",
        (settings.DEFAULT_HOTEL_ID, user["id"], str(table_id), auth.now_iso()),
    )
    return {"token": token}


# --- admin: printable QR pages --------------------------------------------
def _qr_card_html(table_name: str, token: str, base_url: str) -> str:
    # Maximum scan reliability: NO centre overlay at all - 100% unobstructed
    # black-and-white modules. Error correction H and a white quiet-zone border
    # (margin ~4 modules) so any phone camera reads it first time.
    url = f"{base_url}/static/customer.html?token={token}"
    return f"""
    <div class="qr-card">
      <div id="qr-{token}"></div>
      <h2>{table_name}</h2>
      <p>Scan to order</p>
    </div>
    <script>
      new QRCodeStyling({{
        width: 240, height: 240, type: 'svg',
        data: {url!r},
        errorCorrectionLevel: 'H',
        margin: 24,
        dotsOptions: {{ color: '#000000', type: 'square' }},
        backgroundOptions: {{ color: '#ffffff' }},
        cornersSquareOptions: {{ color: '#000000', type: 'square' }}
      }}).append(document.getElementById('qr-{token}'));
    </script>
    """


def _print_page(title: str, cards: str) -> HTMLResponse:
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{title}</title>
<script src="https://cdn.jsdelivr.net/npm/qr-code-styling@1.6.0/lib/qr-code-styling.js"></script>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 0; padding: 20px; background:#fafafa; }}
  .toolbar {{ margin-bottom: 16px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(260px,1fr)); gap: 16px; }}
  .qr-card {{ background:#fff; border:1px solid #ddd; border-radius:12px; padding:16px; text-align:center; }}
  .qr-logo {{ font-size: 28px; }}
  .qr-card h2 {{ margin: 8px 0 2px; }}
  .qr-card p {{ margin: 0; color:#666; }}
  @media print {{ .toolbar {{ display:none; }} body {{ background:#fff; }} }}
</style></head>
<body>
  <div class="toolbar"><button onclick="window.print()">Print</button></div>
  <div class="grid">{cards}</div>
</body></html>"""
    return HTMLResponse(html)


def _base_url(request: Request) -> str:
    # Prefer an explicit BASE_URL (so phones open the right host, not 127.0.0.1).
    if settings.BASE_URL:
        return settings.BASE_URL.rstrip("/")
    return str(request.base_url).rstrip("/")


@router.get("/admin/tables/{table_id}/print", response_class=HTMLResponse)
def print_one(table_id: int, request: Request, user=Depends(auth.require_roles("admin"))):
    row = db.query_one("SELECT name, token FROM tables WHERE id = ? AND active = TRUE", (table_id,))
    if not row:
        raise HTTPException(status_code=404, detail="Table not found")
    card = _qr_card_html(row["name"], row["token"], _base_url(request))
    return _print_page(row["name"], card)


@router.get("/admin/tables/print/all", response_class=HTMLResponse)
def print_all(request: Request, user=Depends(auth.require_roles("admin"))):
    rows = db.query_all(
        "SELECT name, token FROM tables WHERE hotel_id = ? AND active = TRUE ORDER BY id",
        (settings.DEFAULT_HOTEL_ID,),
    )
    cards = "".join(_qr_card_html(r["name"], r["token"], _base_url(request)) for r in rows)
    return _print_page("All tables", cards)


# --- public: token landing (no login needed to VIEW) ----------------------
@router.get("/t/{token}")
def table_landing(token: str):
    row = _get_table(token)
    # Soft-deleted (active = 0) or unknown token -> the QR is dead.
    if not row or not row.get("active"):
        raise HTTPException(status_code=404, detail="This table code is not valid")
    return {
        "table_id": row["id"],
        "table_name": row["name"],
        "status": row["status"],
        "valid": True,
    }