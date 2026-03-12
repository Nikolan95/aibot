from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .intent import looks_like_part_request, looks_like_smalltalk
from .logic import detect_vin, _is_choice_number, _normalize_part_name, _wants_new_part  # type: ignore


@dataclass(frozen=True)
class Intent:
    name: str
    confidence: float
    data: dict[str, Any]


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


def classify_intent(*, text: str, order_step: str) -> Intent:
    vin = detect_vin(text)
    if vin:
        return Intent(name="vin", confidence=0.98, data={"vin": vin})

    if _wants_new_vehicle(text):
        return Intent(name="change_vehicle", confidence=0.9, data={})

    if _wants_checkout(text):
        return Intent(name="checkout", confidence=0.85, data={})

    choice = _is_choice_number(text)
    if order_step == "waiting_oem_choice" and choice is not None:
        return Intent(name="select_part", confidence=0.95, data={"choice": choice})

    if _wants_new_part(text):
        return Intent(name="change_part", confidence=0.9, data={})

    if looks_like_part_request(text):
        part = _normalize_part_name(text) or text.strip()
        return Intent(name="part_request", confidence=0.8, data={"part": part})

    if looks_like_smalltalk(text):
        return Intent(name="smalltalk", confidence=0.6, data={})

    return Intent(name="unknown", confidence=0.4, data={})
