from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any


def log_event(event: str, **fields: Any) -> None:
    payload = {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "event": event,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False))

