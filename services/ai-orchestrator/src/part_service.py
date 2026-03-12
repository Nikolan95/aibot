from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from . import config
from .logging_utils import log_event


@dataclass(frozen=True)
class PartsSearchResult:
    code: str | None
    oems: list[str]
    meta: dict[str, Any] | None


def _normalize_sender_id(sender_id: str) -> str:
    s = str(sender_id or "").strip()
    # WhatsApp often sends digits only; dev chat may include '+'.
    digits = "".join(ch for ch in s if ch.isdigit())
    return digits or s


def search_parts(*, token: str, part_name: str, sender_id: str, ret_oem_num: int = 3) -> PartsSearchResult:
    payload = {
        "token": token,
        "partName": part_name,
        "senderId": _normalize_sender_id(sender_id),
        "retOemNum": int(ret_oem_num),
    }

    with httpx.Client(timeout=config.PARTS_SEARCH_TIMEOUT_S) as client:
        if config.DEBUG_EXTERNAL_CALLS:
            log_event(
                "parts_search.request",
                url=config.PARTS_SEARCH_URL,
                partName=part_name,
                senderId_tail=str(sender_id)[-4:],
                retOemNum=int(ret_oem_num),
            )
        r = client.post(config.PARTS_SEARCH_URL, json=payload)
        r.raise_for_status()
        data = r.json()

    oems = data.get("oems")
    oems_norm: list[str] = []
    if isinstance(oems, list):
        for x in oems:
            s = str(x or "").strip()
            if s:
                oems_norm.append(s)
    elif isinstance(oems, dict):
        # older shape: { "OEM": "label" }
        for k in oems.keys():
            s = str(k or "").strip()
            if s:
                oems_norm.append(s)
    elif isinstance(oems, str):
        s = oems.strip()
        if s:
            oems_norm.append(s)

    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = None

    if config.DEBUG_EXTERNAL_CALLS:
        log_event(
            "parts_search.response",
            status=r.status_code,
            code=str(data.get("code") or ""),
            oems_count=len(oems_norm),
        )

    return PartsSearchResult(code=str(data.get("code") or ""), oems=oems_norm, meta=meta)
