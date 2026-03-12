from __future__ import annotations

import re


PART_HINT_RE = re.compile(
    r"\b(brake|pads?|discs?|filter|oil\s*filter|oilfilter|air\s*filter|airfilter|battery|alternator|starter|spark|clutch|belt|pump|radiator|injector|turbo)\b",
    re.IGNORECASE,
)

SMALLTALK_RE = re.compile(
    r"\b(hi|hello|hey|good\s*(morning|afternoon|evening)|thanks|thank\s*you|ok|okay|cool|great|lol)\b",
    re.IGNORECASE,
)

STORE_INFO_RE = re.compile(
    r"\b(brand|brands|opening\s*hours|hours|located|location|contact|email|phone|whatsapp|categories|products)\b",
    re.IGNORECASE,
)

ORDER_VERB_RE = re.compile(
    r"\b(need|want|looking\s*for|order|buy|quote|price|availability|available|fit|fits)\b",
    re.IGNORECASE,
)


def looks_like_part_request(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    # greetings / smalltalk should not trigger VIN gating
    if SMALLTALK_RE.search(t):
        return False
    # store-info questions are not part requests
    if STORE_INFO_RE.search(t):
        return False
    # strong hint: explicit part words
    if PART_HINT_RE.search(t):
        return True
    # otherwise require an "order/need" verb to avoid false positives like "hello"
    return bool(ORDER_VERB_RE.search(t))


def looks_like_smalltalk(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if any(x in t for x in ["hi", "hello", "hey", "thanks", "thank you", "ok", "okay", "cool", "great"]):
        return True
    if t.endswith("?") and len(t) <= 80:
        return True
    if len(t) <= 30:
        return True
    return False
