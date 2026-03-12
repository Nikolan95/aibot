from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from . import config
from .logging_utils import log_event


@dataclass(frozen=True)
class TecdocItem:
    aftermarket_number: str
    brand: str
    title: str
    small_title: str | None
    description: list[str]
    image: str | None
    pdf: str | None


def search_oem(oem: str) -> list[TecdocItem]:
    o = (oem or "").strip()
    if not o:
        return []

    with httpx.Client(timeout=config.TECDOC_SEARCH_OEM_TIMEOUT_S) as client:
        if config.DEBUG_EXTERNAL_CALLS:
            log_event("tecdoc_search_oem.request", url=config.TECDOC_SEARCH_OEM_URL, oem=o)
        r = client.get(config.TECDOC_SEARCH_OEM_URL, params={"oem": o})
        if config.DEBUG_EXTERNAL_CALLS:
            log_event("tecdoc_search_oem.response", status=r.status_code)
        r.raise_for_status()
        data = r.json()

    items = data.get("data")
    if not isinstance(items, list):
        return []

    out: list[TecdocItem] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        aftermarket_number = str(it.get("aftermarket_number") or "").strip()
        brand = str(it.get("brand") or "").strip()
        title = str(it.get("title") or "").strip()
        if not aftermarket_number or not brand or not title:
            continue
        desc = it.get("description")
        if not isinstance(desc, list):
            desc = []
        desc_norm = [str(x).strip() for x in desc if str(x).strip()]
        out.append(
            TecdocItem(
                aftermarket_number=aftermarket_number,
                brand=brand,
                title=title,
                small_title=str(it.get("small_title") or "").strip() or None,
                description=desc_norm,
                image=str(it.get("image") or "").strip() or None,
                pdf=str(it.get("pdf") or "").strip() or None,
            )
        )

    return out
