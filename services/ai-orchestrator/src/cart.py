from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.database import Database


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _ensure_active_cart(db: Database, *, session_id: ObjectId, sender_id: str) -> dict[str, Any]:
    cart = db["chat_carts"].find_one({"session_id": session_id, "status": {"$in": ["active", None]}})
    if cart:
        # normalize missing status for legacy docs
        if not cart.get("status"):
            db["chat_carts"].update_one(
                {"_id": cart["_id"]},
                {"$set": {"status": "active", "updated_at": now_utc()}},
            )
            cart["status"] = "active"
        return cart

    cart_id = uuid.uuid4().hex
    doc = {
        "session_id": session_id,
        "cart_id": cart_id,
        "sender_id": sender_id,
        "status": "active",
        "items": [],
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    db["chat_carts"].insert_one(doc)
    return doc


def get_active_cart_items(db: Database, *, session_id: ObjectId) -> list[dict[str, Any]]:
    cart = db["chat_carts"].find_one({"session_id": session_id, "status": {"$in": ["active", None]}})
    if not cart:
        return []
    items = cart.get("items")
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict):
            out.append(it)
    return out


def checkout_active_cart(db: Database, *, session_id: ObjectId) -> bool:
    cart = db["chat_carts"].find_one({"session_id": session_id, "status": {"$in": ["active", None]}})
    if not cart:
        return False
    db["chat_carts"].update_one(
        {"_id": cart["_id"]},
        {"$set": {"status": "checked_out", "checked_out_at": now_utc(), "updated_at": now_utc()}},
    )
    return True


def add_cart_item(
    db: Database,
    *,
    session_id: ObjectId,
    sender_id: str,
    part_query: str,
    oem: str | None,
    selected_part: dict[str, Any],
    qty: int = 1,
) -> str:
    """
    Upserts chat_carts for a session and appends an item.
    Returns the generated cart item id.
    """
    item_id = uuid.uuid4().hex
    item = {
        "id": item_id,
        "added_at": now_utc(),
        "qty": int(qty),
        "part_query": part_query,
        "oem": oem,
        "title": selected_part.get("title"),
        "brand": selected_part.get("brand"),
        "aftermarket_number": selected_part.get("aftermarket_number"),
        "description": selected_part.get("description") if isinstance(selected_part.get("description"), list) else [],
        "image": selected_part.get("image"),
        "pdf": selected_part.get("pdf"),
    }

    cart = _ensure_active_cart(db, session_id=session_id, sender_id=sender_id)
    db["chat_carts"].update_one(
        {"_id": cart.get("_id"), "session_id": session_id},
        {"$set": {"updated_at": now_utc()}, "$push": {"items": item}},
    )

    return item_id
