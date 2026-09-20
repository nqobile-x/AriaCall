from __future__ import annotations

import hashlib
import time
from threading import Lock

_LOCK = Lock()
_STORE: dict[str, tuple[dict, float]] = {}  # key -> (result, expires_at)
_TTL = 1800  # 30 minutes


def _key(company_id: str, message: str) -> str:
    normalized = " ".join(message.lower().split())
    raw = f"{company_id}::{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get(company_id: str, message: str) -> dict | None:
    k = _key(company_id, message)
    with _LOCK:
        entry = _STORE.get(k)
        if entry and time.monotonic() < entry[1]:
            return entry[0]
        if entry:
            del _STORE[k]
    return None


def set(company_id: str, message: str, result: dict, ttl: int = _TTL) -> None:
    k = _key(company_id, message)
    with _LOCK:
        _STORE[k] = (result, time.monotonic() + ttl)


def stats() -> dict:
    now = time.monotonic()
    with _LOCK:
        live = sum(1 for _, exp in _STORE.values() if now < exp)
        return {"entries": len(_STORE), "live": live}
