"""Menu management (admin) + public menu view (customers).

Categories group items. Items have name, category, price in whole KES, photo,
description and an active flag. Prices are decided on the SERVER (source of
truth); the phone only ever sends a menu_item id and quantity.

Photos: an uploaded file is saved under static/uploads/ and served as a URL.
We do not store big image blobs in the database.
"""
import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import auth, db
from ..config import settings

router = APIRouter(tags=["menu"])

UPLOAD_DIR = os.path.join("static", "uploads")


# --- schemas ---------------------------------------------------------------
class CategoryIn(BaseModel):
    name: str
    sort_order: int = 0


class ItemIn(BaseModel):
    name: str
    category_id: int | None = None
    price_kes: int
    description: str | None = None
    photo_url: str | None = None
    active: bool = True


# --- categories (admin) ---------------------------------------------------
@router.get("/admin/categories")
def list_categories(user=Depends(auth.require_roles("admin"))):
    return db.query_all(
        "SELECT id, name, sort_order FROM categories WHERE hotel_id = ? ORDER BY sort_order, id",
        (settings.DEFAULT_HOTEL_ID,),
    )


@router.post("/admin/categories", status_code=201)
def add_category(body: CategoryIn, user=Depends(auth.require_roles("admin"))):
    new_id = db.execute_returning_id(
        "INSERT INTO categories (hotel_id, name, sort_order) VALUES (?, ?, ?)",
        (settings.DEFAULT_HOTEL_ID, body.name, body.sort_order),
    )
    return {"id": new_id, "name": body.name}


@router.patch("/admin/categories/{category_id}")
def edit_category(category_id: int, body: CategoryIn, user=Depends(auth.require_roles("admin"))):
    db.execute(
        "UPDATE categories SET name = ?, sort_order = ? WHERE id = ? AND hotel_id = ?",
        (body.name, body.sort_order, category_id, settings.DEFAULT_HOTEL_ID),
    )
    return {"ok": True}


@router.delete("/admin/categories/{category_id}")
def delete_category(category_id: int, user=Depends(auth.require_roles("admin"))):
    db.execute("DELETE FROM categories WHERE id = ? AND hotel_id = ?",
               (category_id, settings.DEFAULT_HOTEL_ID))
    return {"ok": True}


# --- menu items (admin) ---------------------------------------------------
@router.get("/admin/menu")
def list_items_admin(user=Depends(auth.require_roles("admin"))):
    return db.query_all(
        "SELECT id, category_id, name, description, price_kes, photo_url, active "
        "FROM menu_items WHERE hotel_id = ? ORDER BY category_id, id",
        (settings.DEFAULT_HOTEL_ID,),
    )


@router.post("/admin/menu", status_code=201)
def add_item(body: ItemIn, user=Depends(auth.require_roles("admin"))):
    if body.price_kes < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    new_id = db.execute_returning_id(
        "INSERT INTO menu_items "
        "(hotel_id, category_id, name, description, price_kes, photo_url, active, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            settings.DEFAULT_HOTEL_ID, body.category_id, body.name, body.description,
            body.price_kes, body.photo_url, body.active, auth.now_iso(),
        ),
    )
    return {"id": new_id}


@router.patch("/admin/menu/{item_id}")
def edit_item(item_id: int, body: ItemIn, user=Depends(auth.require_roles("admin"))):
    if body.price_kes < 0:
        raise HTTPException(status_code=400, detail="Price cannot be negative")
    db.execute(
        "UPDATE menu_items SET category_id = ?, name = ?, description = ?, price_kes = ?, "
        "photo_url = ?, active = ? WHERE id = ? AND hotel_id = ?",
        (
            body.category_id, body.name, body.description, body.price_kes,
            body.photo_url, body.active, item_id, settings.DEFAULT_HOTEL_ID,
        ),
    )
    return {"ok": True}


@router.delete("/admin/menu/{item_id}")
def delete_item(item_id: int, user=Depends(auth.require_roles("admin"))):
    # Hide instead of hard-delete so old order_items keep their snapshot.
    db.execute("UPDATE menu_items SET active = FALSE WHERE id = ? AND hotel_id = ?",
               (item_id, settings.DEFAULT_HOTEL_ID))
    return {"ok": True}


# --- photo upload (admin) -------------------------------------------------
@router.post("/admin/menu/upload")
async def upload_photo(file: UploadFile = File(...), user=Depends(auth.require_roles("admin"))):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1].lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Only jpg/png/webp images")
    name = f"{uuid.uuid4().hex}{ext}"
    path = os.path.join(UPLOAD_DIR, name)
    with open(path, "wb") as out:
        out.write(await file.read())
    return {"photo_url": f"/static/uploads/{name}"}


# --- public menu (customers, no login) ------------------------------------
@router.get("/menu")
def public_menu():
    """Full menu for the default hotel, grouped by category. Active items only."""
    categories = db.query_all(
        "SELECT id, name FROM categories WHERE hotel_id = ? ORDER BY sort_order, id",
        (settings.DEFAULT_HOTEL_ID,),
    )
    items = db.query_all(
        "SELECT id, category_id, name, description, price_kes, photo_url "
        "FROM menu_items WHERE hotel_id = ? AND active = TRUE ORDER BY category_id, id",
        (settings.DEFAULT_HOTEL_ID,),
    )
    return {"categories": categories, "items": items}