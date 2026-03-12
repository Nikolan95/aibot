from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from . import config


@dataclass(frozen=True)
class PartsSearchResult:
    code: str | None
    oems: dict[str, str]
    meta: dict[str, Any] | None


def search_parts(*, token: str, part_name: str, sender_id: str, ret_oem_num: int = 3) -> PartsSearchResult:
    payload = {
        "token": token,
        "partName": part_name,
        "senderId": sender_id,
        "retOemNum": int(ret_oem_num),
    }

    with httpx.Client(timeout=config.PARTS_SEARCH_TIMEOUT_S) as client:
        r = client.post(config.PARTS_SEARCH_URL, json=payload)
        r.raise_for_status()
        data = r.json()

    oems = data.get("oems")
    if not isinstance(oems, dict):
        oems = {}

    # normalize to str->str
    oems_norm: dict[str, str] = {}
    for k, v in oems.items():
        if k is None or v is None:
            continue
        oems_norm[str(k)] = str(v)

    meta = data.get("meta")
    if not isinstance(meta, dict):
        meta = None

    return PartsSearchResult(code=str(data.get("code") or ""), oems=oems_norm, meta=meta)

