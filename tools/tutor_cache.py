"""In-memory cache for complete mentor answers.

Why: a "Teach me" request for the same lesson is identical for every learner, and a repeated
Review of the same code is identical too. Serving those from memory costs no API call, no model
thread and no waiting, which is what keeps a small Render instance calm under classroom load.

Rules
- Only complete answers from the cloud model are stored (never offline guidance, local-model
  output, partial streams or errors).
- Bounded (LRU) and expiring, so memory stays small and stale answers age out.
- The key is a hash of the whole prompt (language, level, mode, code, question, lesson, findings).
  Nothing is written to disk. Set TUTOR_CACHE=off to disable.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict

MAX_ENTRIES = 300
TTL_SECONDS = 6 * 3600
MIN_ANSWER_CHARS = 40
MAX_ANSWER_CHARS = 20_000


class ResponseCache:
    def __init__(self, max_entries: int = MAX_ENTRIES, ttl: float = TTL_SECONDS, clock=time.monotonic) -> None:
        self.max_entries = max_entries
        self.ttl = ttl
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def enabled() -> bool:
        return os.getenv("TUTOR_CACHE", "on").strip().lower() not in {"0", "off", "false", "no"}

    @staticmethod
    def key(messages: list[dict]) -> str:
        return hashlib.sha256(json.dumps(messages, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()

    def get(self, key: str) -> str | None:
        if not self.enabled():
            return None
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self.misses += 1
                return None
            stored_at, text = item
            if self._clock() - stored_at > self.ttl:
                del self._data[key]
                self.misses += 1
                return None
            self._data.move_to_end(key)
            self.hits += 1
            return text

    def set(self, key: str, text: str) -> None:
        if not self.enabled() or not (MIN_ANSWER_CHARS <= len(text) <= MAX_ANSWER_CHARS):
            return
        with self._lock:
            self._data[key] = (self._clock(), text)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self.hits = self.misses = 0

    def stats(self) -> dict:
        with self._lock:
            total = self.hits + self.misses
            return {"entries": len(self._data), "hits": self.hits, "misses": self.misses, "hit_rate": round(self.hits / total, 2) if total else 0.0}


cache = ResponseCache()
