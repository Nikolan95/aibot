import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from .faq import search_faq
from .intent import looks_like_part_request, looks_like_smalltalk
from .openai_client import get_llm_config, llm_reply
from .part_service import search_parts
from .vin_service import check_vin

VIN_RE = re.compile(r"\b([A-HJ-NPR-Z0-9]{17})\b", re.IGNORECASE)


def detect_vin(text: str) -> str | None:
    match = VIN_RE.search(text or "")
    if not match:
        return None
    return match.group(1).upper()


def now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def get_session(db: Database, session_id: str) -> dict[str, Any] | None:
    return db["chat_sessions"].find_one({"_id": ObjectId(session_id)})


def get_last_messages(db: Database, session_id: str, limit: int) -> list[dict[str, Any]]:
    return list(
        db["chat_messages"]
        .find({"session_id": ObjectId(session_id)})
        .sort("timestamp", -1)
        .limit(limit)
    )[::-1]


def update_session_data(db: Database, session_id: str, patch: dict[str, Any]) -> None:
    db["chat_sessions"].update_one({"_id": ObjectId(session_id)}, {"$set": patch})


def ensure_order(session_data: dict[str, Any]) -> dict[str, Any]:
    order = session_data.get("order")
    if not isinstance(order, dict):
        order = {}
    order.setdefault("step", "waiting_part_name")
    order.setdefault("items", [])
    order.setdefault("delivery_address", None)
    order.setdefault("payment_method", None)
    order.setdefault("total_price", None)
    order.setdefault("status", "draft")
    return order


def _needs_part_details(part_name: str) -> bool:
    p = (part_name or "").lower()
    return any(
        k in p
        for k in [
            "brake pad",
            "brake pads",
            "brake disc",
            "brake discs",
            "disc",
            "pads",
            "filter",
            "oil",
            "spark plug",
            "battery",
        ]
    )


def _normalize_part_name(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    t = re.sub(r"(?i)\b(i\s*(would\s*like|want|need)|lets\s*see|please|plz)\b", " ", t)
    t = re.sub(r"(?i)\b(do\s*you\s*have|have\s*you\s*got|can\s*you\s*get)\b", " ", t)
    t = re.sub(
        r"(?i)\b(give\s*me|send\s*me)\s*(the\s*)?(oem|oem\s*number|oem\s*numbers)\s*(for)?\b",
        " ",
        t,
    )
    t = re.sub(r"(?i)[^a-z0-9\s\-_/]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    words = t.split(" ")
    if len(words) > 6:
        t = " ".join(words[-6:])
    return t.strip()


def _parts_search_messages(oems: dict[str, str]) -> list[str]:
    msgs: list[str] = []
    for idx, (oem, label) in enumerate(list(oems.items())[:3], start=1):
        msgs.append(f"{idx}) {oem}: {label}")
    msgs.append("Reply with the option number (1-3) you want, or tell me to search again with a different part name.")
    return msgs


def generate_reply_and_session_patch(
    db: Database, session: dict[str, Any], incoming_text: str
) -> tuple[list[str], dict[str, Any]]:
    session_data = session.get("session_data") or {}
    if not isinstance(session_data, dict):
        session_data = {}

    patch: dict[str, Any] = {}

    # Initialize order state early so we can prioritize order-step replies over FAQ/smalltalk.
    order = ensure_order(session_data)
    step = str(order.get("step") or "waiting_part_name")

    vin = detect_vin(incoming_text)
    if vin:
        try:
            res = check_vin(vin)
        except Exception:
            vehicle = session_data.get("vehicle")
            if not isinstance(vehicle, dict):
                vehicle = {}
            vehicle.update({"vin": vin, "checked_at": now_utc(), "ok": None})
            patch["session_data.vehicle"] = vehicle
            return (["I received your VIN, but I can’t verify it right now. Please try again in a moment."], patch)

        vehicle = session_data.get("vehicle")
        if not isinstance(vehicle, dict):
            vehicle = {}
        vehicle.update(
            {
                "vin": res.vin,
                "checked_at": now_utc(),
                "ok": res.ok,
                "token": res.token,
                "meta": res.meta,
            }
        )

        patch["vin"] = res.vin
        patch["session_data.vehicle"] = vehicle
        order = ensure_order(session_data)
        patch["session_data.order"] = order

        if res.ok and res.token:
            pending = session_data.get("pending_part")
            pending_name = ""
            if isinstance(pending, dict):
                pending_name = str(pending.get("name") or "").strip()

            # If the user already asked for a part before sending VIN, continue without asking again.
            sender_id = str(session.get("sender_id") or "")
            if pending_name and sender_id:
                try:
                    parts = search_parts(
                        token=res.token,
                        part_name=pending_name,
                        sender_id=sender_id,
                        ret_oem_num=3,
                    )
                except Exception:
                    patch["session_data.pending_part"] = None
                    return (
                        [
                            f"Vehicle found for VIN {res.vin}. What car part do you need?",
                        ],
                        patch,
                    )

                candidates = [{"oem": k, "label": v} for k, v in list(parts.oems.items())[:3]]
                if order.get("items"):
                    order["items"][0]["name"] = pending_name
                else:
                    order["items"] = [{"name": pending_name, "qty": None, "details": None, "candidates": []}]
                order["items"][0]["candidates"] = candidates
                order["step"] = "waiting_oem_choice" if candidates else "waiting_part_name"
                patch["session_data.order"] = order
                patch["session_data.pending_part"] = None

                if not candidates:
                    return (
                        [
                            f"Vehicle found for VIN {res.vin}, but I couldn’t determine OEM numbers for “{pending_name}”. Please send a different part name.",
                        ],
                        patch,
                    )
                return (_parts_search_messages(parts.oems), patch)

            return ([f"Vehicle found for VIN {res.vin}. What car part do you need?"], patch)

        return ([f"I couldn’t find a vehicle for VIN {res.vin}. Please double-check the VIN and send it again."], patch)

    # If we're in a structured order step, do NOT let FAQ matching steal the user's reply.
    if step == "waiting_oem_choice":
        choice = incoming_text.strip().lower()
        m = re.search(r"\b([1-3])\b", choice)
        if not m:
            patch["session_data.order"] = order
            return (["Please reply with 1, 2, or 3 (the option number)."], patch)
        idx = int(m.group(1)) - 1
        items = order.get("items") or []
        if not items:
            order["step"] = "waiting_part_name"
            patch["session_data.order"] = order
            return (["What part do you need?"], patch)
        candidates = items[0].get("candidates") or []
        if not isinstance(candidates, list) or idx >= len(candidates):
            patch["session_data.order"] = order
            return (["That option isn’t available. Reply with 1, 2, or 3."], patch)
        items[0]["selected_oem"] = candidates[idx].get("oem")
        order["items"] = items
        order["step"] = "waiting_quantity"
        patch["session_data.order"] = order
        return ([f"Selected OEM {items[0]['selected_oem']}. How many do you need?"], patch)

    if step == "confirm_order":
        answer = incoming_text.strip().lower()
        if answer in {"yes", "y", "confirm", "ok"}:
            order["status"] = "confirmed"
            order["step"] = "done"
            patch["session_data.order"] = order
            return (["Confirmed. Thanks! We’ll get back to you with availability and pricing."], patch)
        if answer in {"no", "n", "cancel"}:
            order["status"] = "draft"
            order["step"] = "waiting_part_name"
            order["items"] = []
            order["delivery_address"] = None
            patch["session_data.order"] = order
            return (["Canceled. What part do you need?"], patch)
        patch["session_data.order"] = order
        return (["Please reply YES to confirm or NO to cancel."], patch)

    faq = search_faq(db, incoming_text)
    if faq:
        if "PLEASE INSERT" in faq.answer.upper():
            return (
                [
                    "I don’t have the full returns policy text yet. If you want, tell me what you need to return and I’ll connect you with support."
                ],
                {},
            )
        patch = {"session_data.last_faq": {"question": faq.question, "answered_at": now_utc()}}
        return ([faq.answer], patch)

    vehicle = session_data.get("vehicle")
    has_vehicle = isinstance(vehicle, dict) and bool(vehicle.get("vin"))

    # If we don't have a vehicle yet, avoid hard-gating every message behind VIN.
    # Use the LLM for smalltalk/general questions; still ask for VIN for part requests.
    if not has_vehicle:
        if looks_like_part_request(incoming_text):
            part_guess = _normalize_part_name(incoming_text)
            if part_guess:
                patch["session_data.pending_part"] = {"name": part_guess, "captured_at": now_utc()}
            patch["session_data.order"] = ensure_order(session_data)
            return (
                [
                    "To match the correct part, please send your 17-character VIN (or a photo of the vehicle card). Then tell me the part name."
                ],
                patch,
            )

        llm_cfg = get_llm_config()
        if llm_cfg.enabled and looks_like_smalltalk(incoming_text):
            last_faq = session_data.get("last_faq")
            last_faq_q = ""
            if isinstance(last_faq, dict):
                last_faq_q = str(last_faq.get("question") or "")

            # Pull a few more FAQ entries to ground answers (even if no strong match).
            faqs = list(
                db["faqs"]
                .find({"enabled": {"$ne": False}}, {"_id": 0, "question": 1, "answer": 1})
                .limit(12)
            )
            faq_blob = "\n".join(
                [f"- Q: {f.get('question','')}\n  A: {f.get('answer','')}" for f in faqs]
            )

            system = (
                "You are a helpful, friendly car parts sales assistant for MotoParts. "
                "Keep replies brief (1-3 short sentences). Ask at most one question. "
                "If the user asks about store info, use the provided FAQ facts only. "
                "If you are unsure, say so and suggest contacting support. "
                "If the user wants to order a part, ask for VIN and the part needed."
            )
            user = (
                f"User message: {incoming_text}\n"
                f"Last FAQ topic (if any): {last_faq_q}\n\n"
                f"FAQ facts:\n{faq_blob}\n"
            )
            llm_text = llm_reply(model=llm_cfg.model, system=system, user=user)
            if llm_text:
                return ([llm_text], {})

    if not has_vehicle:
        patch["session_data.order"] = order
        return (
            ["Please send your 17-character VIN (or a photo of the vehicle card) so I can match the correct part."],
            patch,
        )

    if step == "waiting_part_name":
        raw_part = incoming_text.strip()
        part_name = _normalize_part_name(raw_part) or raw_part
        if not part_name:
            return (["What part do you need?"], {"session_data.order": order})
        order["items"] = [{"name": part_name, "qty": None, "details": None, "candidates": []}]

        # Call parts search immediately if we have a VIN token saved (no extra questions).
        vehicle = session_data.get("vehicle")
        token = ""
        if isinstance(vehicle, dict):
            token = str(vehicle.get("token") or "")
        sender_id = str(session.get("sender_id") or "")

        if token and sender_id:
            try:
                res = search_parts(token=token, part_name=part_name, sender_id=sender_id, ret_oem_num=3)
            except Exception:
                order["step"] = "waiting_part_name"
                patch["session_data.order"] = order
                return (
                    ["I couldn’t search parts right now. Please try a different part name (e.g. “oil filter”)."],
                    patch,
                )

            candidates = [{"oem": k, "label": v} for k, v in list(res.oems.items())[:3]]
            order["items"][0]["candidates"] = candidates
            order["step"] = "waiting_oem_choice" if candidates else "waiting_part_name"
            patch["session_data.order"] = order

            if not candidates:
                return (["I couldn’t determine OEM numbers for that part. Try a different name (e.g. “oil filter”)."], patch)

            return (_parts_search_messages(res.oems), patch)

        # If no token yet, fall back to asking for VIN / clarification.
        if _needs_part_details(part_name):
            order["step"] = "waiting_part_details"
            patch["session_data.order"] = order
            return (["Please send the part name (e.g. “oil filter”)."], patch)

        order["step"] = "waiting_quantity"
        patch["session_data.order"] = order
        return ([f"Got it: {part_name}. How many do you need?"], patch)

    if step == "waiting_part_details":
        raw_part = incoming_text.strip()
        part_name = _normalize_part_name(raw_part) or raw_part
        if not part_name:
            patch["session_data.order"] = order
            return (["Please send the part name (e.g. “oil filter”)."], patch)

        if not order.get("items"):
            order["items"] = [{"name": part_name, "qty": None, "details": None, "candidates": []}]
        else:
            order["items"][0]["name"] = part_name

        vehicle = session_data.get("vehicle")
        token = ""
        if isinstance(vehicle, dict):
            token = str(vehicle.get("token") or "")
        sender_id = str(session.get("sender_id") or "")

        if token and sender_id:
            try:
                res = search_parts(token=token, part_name=part_name, sender_id=sender_id, ret_oem_num=3)
            except Exception:
                order["step"] = "waiting_part_name"
                patch["session_data.order"] = order
                return (["I couldn’t search parts right now. Try a different part name (e.g. “oil filter”)."], patch)

            candidates = [{"oem": k, "label": v} for k, v in list(res.oems.items())[:3]]
            order["items"][0]["candidates"] = candidates
            order["step"] = "waiting_oem_choice" if candidates else "waiting_part_name"
            patch["session_data.order"] = order
            if not candidates:
                return (["I couldn’t determine OEM numbers for that part. Try a different name (e.g. “oil filter”)."], patch)
            return (_parts_search_messages(res.oems), patch)

        order["step"] = "waiting_part_name"
        patch["session_data.order"] = order
        return (["Please send your VIN first so I can search the correct OEMs."], patch)

    if step == "waiting_quantity":
        m = re.search(r"\b(\d{1,3})\b", incoming_text)
        if not m:
            patch["session_data.order"] = order
            return (["Please reply with a quantity (e.g. 1 or 2)."], patch)
        qty = int(m.group(1))
        if not order.get("items"):
            order["items"] = [{"name": "part", "qty": qty, "details": None, "candidates": []}]
        else:
            order["items"][0]["qty"] = qty
        order["step"] = "waiting_delivery_address"
        patch["session_data.order"] = order
        return (["Thanks. What delivery address should we use?"], patch)

    if step == "waiting_delivery_address":
        addr = incoming_text.strip()
        if not addr:
            patch["session_data.order"] = order
            return (["Please send the delivery address."], patch)
        order["delivery_address"] = addr
        order["step"] = "confirm_order"
        patch["session_data.order"] = order
        item = (order.get("items") or [{}])[0]
        part = item.get("name", "part")
        qty = item.get("qty", 1)
        vin_value = (vehicle or {}).get("vin", "")
        return (
            [
                f"Please confirm: VIN {vin_value}, Part: {part}, Qty: {qty}, Address: {addr}. Reply YES to confirm or NO to cancel."
            ],
            patch,
        )

    patch["session_data.order"] = order
    return (["What part do you need?"], patch)
