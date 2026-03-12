import re
from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from .faq import search_faq
from .intent import looks_like_part_request, looks_like_smalltalk
from .openai_client import get_llm_config, llm_reply
from .part_service import search_parts
from .tecdoc_service import search_oem
from .vin_service import check_vin
from .cart import add_cart_item, checkout_active_cart, get_active_cart_items

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
    t = re.sub(r"(?i)\b(i\s*would\s*like\s*to)\b", " ", t)
    t = re.sub(r"(?i)\b(order|buy)\b", " ", t)
    t = re.sub(r"(?i)\b(do\s*you\s*have|have\s*you\s*got|can\s*you\s*get)\b", " ", t)
    t = re.sub(
        r"(?i)\b(give\s*me|send\s*me)\s*(the\s*)?(oem|oem\s*number|oem\s*numbers)\s*(for)?\b",
        " ",
        t,
    )
    t = re.sub(r"(?i)\b(for\s*my\s*(car|vehicle)|for\s*(my\s*)?car|for\s*(my\s*)?vehicle)\b", " ", t)
    t = re.sub(r"(?i)[^a-z0-9\s\-_/]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # common typos / variants
    t = re.sub(r"(?i)\bbreak\s+pads?\b", "brake pads", t)
    t = re.sub(r"(?i)\boilfiter\b", "oil filter", t)
    t = re.sub(r"(?i)\boilfilter\b", "oil filter", t)
    words = t.split(" ")
    if len(words) > 6:
        t = " ".join(words[-6:])
    return t.strip()


def _parts_search_messages(oems: list[str]) -> list[str]:
    # Legacy helper (OEM-only). Kept for fallback.
    msgs: list[str] = []
    if oems:
        msgs.append(f"OEM: {oems[0]}")
    return msgs


def _format_desc(desc: list[str]) -> str:
    if not desc:
        return ""
    return "; ".join(desc[:5])


def _tecdoc_messages(items: list[dict[str, Any]]) -> list[str]:
    msgs: list[str] = []
    for idx, it in enumerate(items[:3], start=1):
        title = str(it.get("title") or "").strip()
        desc = it.get("description") or []
        desc_s = _format_desc(desc if isinstance(desc, list) else [])
        if desc_s:
            msgs.append(f"{idx}) {title}\n{desc_s}")
        else:
            msgs.append(f"{idx}) {title}")
    msgs.append("Reply with the option number (1-3) you want, or type a new part name to search again.")
    return msgs


def _lookup_tecdoc_from_oem(oem: str) -> list[dict[str, Any]]:
    items = search_oem(oem)
    out: list[dict[str, Any]] = []
    for it in items[:3]:
        out.append(
            {
                "aftermarket_number": it.aftermarket_number,
                "brand": it.brand,
                "title": it.title,
                "description": it.description,
                "image": it.image,
                "pdf": it.pdf,
            }
        )
    return out


def _part_query_variants(part_name: str) -> list[str]:
    base = _normalize_part_name(part_name) or (part_name or "").strip()
    if not base:
        return []
    variants = [base]

    # extra lightweight expansions
    if "brake pads" in base.lower():
        variants.append("bremsbeläge")
        variants.append("bremsbelag")
        variants.append("bremsbeläge vorne")
        variants.append("vorne bremsbeläge")
        variants.append("front brake pads")
    if "brake disc" in base.lower() or "bremsscheib" in base.lower():
        variants.append("bremsscheiben")
        variants.append("front brake disc")

    # de-dup
    out: list[str] = []
    seen: set[str] = set()
    for v in variants:
        vv = v.strip()
        if not vv or vv.lower() in seen:
            continue
        seen.add(vv.lower())
        out.append(vv)
    return out[:4]


def _search_oem_then_tecdoc(*, token: str, sender_id: str, part_name: str) -> tuple[str, list[dict[str, Any]]] | None:
    for q in _part_query_variants(part_name):
        res = search_parts(token=token, part_name=q, sender_id=sender_id, ret_oem_num=1)
        first_oem = res.oems[0] if res.oems else ""
        if not first_oem:
            continue
        tecdoc_candidates = _lookup_tecdoc_from_oem(first_oem)
        return (q, tecdoc_candidates)
    return None


def _wants_new_part(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return any(
        p in t
        for p in [
            "different part",
            "another part",
            "new part",
            "change part",
            "search again",
            "something else",
        ]
    )


def _wants_new_vehicle(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return any(
        p in t
        for p in [
            "different car",
            "another car",
            "new car",
            "other car",
            "different vehicle",
            "another vehicle",
            "other vehicle",
            "change car",
            "change vehicle",
            "use different vin",
            "try different vin",
        ]
    )


def _wants_checkout(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    return any(
        p in t
        for p in [
            "that would be all",
            "that's all",
            "thats all",
            "that's it",
            "thats it",
            "done",
            "checkout",
            "no more",
            "nothing else",
            "finish",
            "complete order",
        ]
    )


def _checkout_flow(db: Database, *, session: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    session_id = session.get("_id")
    if not isinstance(session_id, ObjectId):
        return (["I couldn’t finalize the order right now. Please try again."], {})

    items = get_active_cart_items(db, session_id=session_id)
    if not items:
        # Don't close the session if there's nothing in the cart.
        return (["Your cart is empty — tell me what part you need (and send your VIN if you haven’t yet)."], {})

    try:
        checkout_active_cart(db, session_id=session_id)
    except Exception:
        return (["I couldn’t finalize the cart right now. Please try again in a moment."], {})

    # Mark session inactive and clear state so the next inbound message starts fresh.
    patch: dict[str, Any] = {
        "active": False,
        "vin": "",
        "session_data": {},
    }

    msg = (
        "Thanks for shopping with MotoParts! Your requested parts will be ready for pickup the next business day in our store "
        "(Kunerolgasse 1A, 1230 Vienna). If you message us again, we can start a new order anytime."
    )
    return ([msg], patch)


def _is_choice_number(text: str) -> int | None:
    m = re.match(r"^\s*([1-3])\s*[\)\.]?\s*$", (text or ""))
    if not m:
        return None
    return int(m.group(1))


def _reset_order_for_new_part(order: dict[str, Any]) -> dict[str, Any]:
    order["step"] = "waiting_part_name"
    order["status"] = "draft"
    order["items"] = []
    order["delivery_address"] = None
    return order


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

    # If a session was checked out previously, any new message reactivates it and restarts from scratch.
    # (Gateway also sets active=true on inbound; this is a defensive fallback.)
    if session.get("active") is False:
        patch["active"] = True
        patch["vin"] = ""
        patch["session_data"] = {}
        session_data = {}
        order = ensure_order(session_data)
        step = str(order.get("step") or "waiting_part_name")

    if _wants_checkout(incoming_text):
        return _checkout_flow(db, session=session)

    vin = detect_vin(incoming_text)
    if vin:
        # If VIN changes mid-conversation, reset order state for the new vehicle.
        current_vehicle = session_data.get("vehicle")
        current_vin = str(current_vehicle.get("vin") or "").upper() if isinstance(current_vehicle, dict) else ""
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
        if current_vin and current_vin != res.vin:
            order = _reset_order_for_new_part(order)
            patch["session_data.pending_part"] = None
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
                    found = _search_oem_then_tecdoc(token=res.token, sender_id=sender_id, part_name=pending_name)
                except Exception:
                    patch["session_data.pending_part"] = None
                    return (
                        [
                            f"Vehicle found for VIN {res.vin}. What car part do you need?",
                        ],
                        patch,
                    )

                if not found:
                    # Keep the pending part so the user can rephrase without losing context.
                    order["step"] = "waiting_part_name"
                    patch["session_data.order"] = order
                    return (
                        [
                            f"Vehicle found for VIN {res.vin}, but I couldn’t find an OEM for “{pending_name}”. Try a different part name (e.g. “brake pads” / “bremsbeläge”)."
                        ],
                        patch,
                    )

                if order.get("items"):
                    order["items"][0]["name"] = pending_name
                else:
                    order["items"] = [{"name": pending_name, "qty": None, "details": None, "candidates": []}]

                used_query, tecdoc_candidates = found
                order["items"][0]["query"] = used_query
                order["items"][0]["candidates"] = tecdoc_candidates
                order["step"] = "waiting_oem_choice" if tecdoc_candidates else "waiting_part_name"
                patch["session_data.order"] = order
                patch["session_data.pending_part"] = None

                if not tecdoc_candidates:
                    return (
                        [
                            f"Vehicle found for VIN {res.vin}, but I couldn’t fetch TecDoc parts for “{pending_name}”. Please type a different part name to search again.",
                        ],
                        patch,
                    )
                return (_tecdoc_messages(tecdoc_candidates), patch)

            return ([f"Vehicle found for VIN {res.vin}. What car part do you need?"], patch)

        return ([f"I couldn’t find a vehicle for VIN {res.vin}. Please double-check the VIN and send it again."], patch)

    if _wants_new_vehicle(incoming_text):
        order = _reset_order_for_new_part(order)
        patch["session_data.order"] = order
        patch["session_data.vehicle"] = {}
        patch["session_data.pending_part"] = None
        patch["vin"] = ""
        return (["Sure — please send the VIN for the other car."], patch)

    # Allow starting a new part flow at any time (keeps VIN/token).
    if _wants_new_part(incoming_text):
        order = _reset_order_for_new_part(order)
        patch["session_data.order"] = order
        return (["Sure — what part do you need?"], patch)

    # If we're in a structured order step, do NOT let FAQ matching steal the user's reply.
    if step == "waiting_oem_choice":
        if _wants_new_part(incoming_text):
            order = _reset_order_for_new_part(order)
            patch["session_data.order"] = order
            return (["No problem — what part should I search for instead?"], patch)

        n = _is_choice_number(incoming_text)
        if n is not None:
            idx = n - 1
            items = order.get("items") or []
            if not items:
                order["step"] = "waiting_part_name"
                patch["session_data.order"] = order
                return (["What part do you need?"], patch)
            candidates = items[0].get("candidates") or []
            if not isinstance(candidates, list) or idx >= len(candidates):
                patch["session_data.order"] = order
                return (["That option isn’t available. Reply with 1, 2, or 3."], patch)

            items[0]["selected_part"] = candidates[idx]
            order["items"] = items
            try:
                add_cart_item(
                    db,
                    session_id=session["_id"],
                    sender_id=str(session.get("sender_id") or ""),
                    part_query=str(items[0].get("query") or items[0].get("name") or ""),
                    oem=str(items[0].get("oem") or "") or None,
                    selected_part=items[0]["selected_part"],
                    qty=1,
                )
            except Exception:
                patch["session_data.order"] = order
                return (["I selected it, but I couldn’t add it to the cart. Please try again."], patch)

            title = str((items[0].get("selected_part") or {}).get("title") or "the selected part")
            order = _reset_order_for_new_part(order)
            patch["session_data.order"] = order
            return ([f"Added to cart: {title}. Do you want anything else?"], patch)

        # Not a selection; if it looks like a new part name, restart search.
        normalized = _normalize_part_name(incoming_text)
        if normalized and re.search(r"[a-zA-Z]", normalized):
            order = _reset_order_for_new_part(order)
            patch["session_data.order"] = order
            step = "waiting_part_name"
        else:
            patch["session_data.order"] = order
            return (["Please reply with 1, 2, or 3 (the option number), or type a new part name."], patch)

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

    # If order is already done/confirmed and user asks for another part, restart order flow.
    if step in {"done"}:
        if _wants_new_part(incoming_text) or _normalize_part_name(incoming_text):
            order = _reset_order_for_new_part(order)
            patch["session_data.order"] = order
            step = "waiting_part_name"

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
                    (
                        f"Got it{': ' + part_guess if part_guess else ''}. "
                        "To match the correct part, please send your 17-character VIN (or a photo of the vehicle card)."
                    )
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
                found = _search_oem_then_tecdoc(token=token, sender_id=sender_id, part_name=part_name)
            except Exception:
                order["step"] = "waiting_part_name"
                patch["session_data.order"] = order
                return (
                    ["I couldn’t search parts right now. Please try a different part name (e.g. “oil filter”)."],
                    patch,
                )

            if not found:
                order["step"] = "waiting_part_name"
                patch["session_data.order"] = order
                return (["I couldn’t find an OEM for that part name. Try something like “brake pads” or “oil filter”."], patch)

            used_query, tecdoc_candidates = found
            order["items"][0]["query"] = used_query
            order["items"][0]["candidates"] = tecdoc_candidates
            order["step"] = "waiting_oem_choice" if tecdoc_candidates else "waiting_part_name"
            patch["session_data.order"] = order

            if not tecdoc_candidates:
                return (
                    [
                        "I found an OEM reference but no TecDoc items came back. Try a different part name.",
                    ],
                    patch,
                )

            return (_tecdoc_messages(tecdoc_candidates), patch)

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
                found = _search_oem_then_tecdoc(token=token, sender_id=sender_id, part_name=part_name)
            except Exception:
                order["step"] = "waiting_part_name"
                patch["session_data.order"] = order
                return (["I couldn’t search parts right now. Try a different part name (e.g. “oil filter”)."], patch)

            if not found:
                order["step"] = "waiting_part_name"
                patch["session_data.order"] = order
                return (["I couldn’t find an OEM for that part name. Try something like “brake pads” or “oil filter”."], patch)

            used_query, tecdoc_candidates = found
            order["items"][0]["query"] = used_query
            order["items"][0]["candidates"] = tecdoc_candidates
            order["step"] = "waiting_oem_choice" if tecdoc_candidates else "waiting_part_name"
            patch["session_data.order"] = order

            if not tecdoc_candidates:
                return (["I found an OEM reference but no TecDoc items came back. Try a different part name."], patch)
            return (_tecdoc_messages(tecdoc_candidates), patch)

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
        selected = item.get("selected_part") if isinstance(item, dict) else None
        if isinstance(selected, dict) and selected.get("title"):
            part = str(selected.get("title"))
        else:
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
