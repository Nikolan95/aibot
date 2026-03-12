from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from . import config


@dataclass(frozen=True)
class VinCheckResult:
    ok: bool
    vin: str
    token: str | None
    meta: dict[str, Any] | None


def check_vin(vin: str) -> VinCheckResult:
    vin_clean = (vin or "").strip().upper()
    if len(vin_clean) != 17:
        return VinCheckResult(ok=False, vin=vin_clean, token=None, meta=None)

    # Dev shortcut: when VIN_DEV_TOKEN is set, skip the external VIN service.
    dev_token = (config.VIN_DEV_TOKEN or "").strip()
    if dev_token:
        return VinCheckResult(ok=True, vin=vin_clean, token=dev_token, meta={"vehicles_count": 1, "source": "dev"})

    with httpx.Client(timeout=config.VIN_CHECK_TIMEOUT_S) as client:
        r = client.post(config.VIN_CHECK_URL, json={"vin": vin_clean})
        r.raise_for_status()
        data = r.json()

    ok = bool(data.get("ok"))
    token = data.get("token")
    meta = data.get("meta")

    return VinCheckResult(
        ok=ok,
        vin=str(data.get("vin") or vin_clean),
        token=str(token) if token else None,
        meta=meta if isinstance(meta, dict) else None,
    )
