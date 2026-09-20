"""Local AI through Ollama: the only path that works with no internet at all.

It is used by the coding mentor when the cloud model is unreachable. Small local models are
much weaker than the cloud model, so answers are labelled and the built-in offline tutor
remains the final safety net. Support-chat wording is deliberately NOT sent to a small
local model: it could invent policies, so chat keeps answering from the knowledge base.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from collections.abc import Iterator

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://127.0.0.1:11434"
PROBE_TTL_SECONDS = 30.0
_lock = threading.Lock()
_probe: dict = {"at": 0.0, "model": None}


def base_url() -> str:
    return (os.getenv("LOCAL_LLM_URL", "").strip() or DEFAULT_URL).rstrip("/")


def enabled() -> bool:
    return os.getenv("LOCAL_LLM", "on").strip().lower() not in {"0", "off", "false", "no"}


def available_model(force: bool = False) -> str | None:
    """Name of the local model to use, or None when Ollama is not running. Cached briefly."""
    if not enabled():
        return None
    now = time.monotonic()
    with _lock:
        if not force and now - _probe["at"] < PROBE_TTL_SECONDS:
            return _probe["model"]
    model = _detect()
    with _lock:
        _probe.update(at=time.monotonic(), model=model)
    return model


def _detect() -> str | None:
    import httpx

    try:
        response = httpx.get(f"{base_url()}/api/tags", timeout=httpx.Timeout(1.0, connect=0.5))
        response.raise_for_status()
        names = [m["name"] for m in response.json().get("models", []) if m.get("name")]
    except Exception:
        return None
    wanted = os.getenv("OLLAMA_MODEL", "").strip()
    if wanted:
        return wanted if wanted in names else None
    chat_models = [n for n in names if "embed" not in n.lower()]
    return chat_models[0] if chat_models else None


def reset_cache() -> None:
    with _lock:
        _probe.update(at=0.0, model=None)


class _ThinkFilter:
    """Drops <think>...</think> reasoning that some local models stream even when told not to."""

    def __init__(self) -> None:
        self.inside = False
        self.buffer = ""

    def feed(self, text: str) -> str:
        self.buffer += text
        out = []
        while self.buffer:
            if self.inside:
                end = self.buffer.find("</think>")
                if end == -1:
                    self.buffer = self.buffer[-8:]
                    return "".join(out)
                self.buffer = self.buffer[end + 8:]
                self.inside = False
            else:
                start = self.buffer.find("<think>")
                if start == -1:
                    keep = max((i for i in range(1, 7) if "<think>".startswith(self.buffer[-i:])), default=0)
                    out.append(self.buffer[: len(self.buffer) - keep])
                    self.buffer = self.buffer[len(self.buffer) - keep:]
                    return "".join(out)
                out.append(self.buffer[:start])
                self.buffer = self.buffer[start + 7:]
                self.inside = True
        return "".join(out)

    def flush(self) -> str:
        rest, self.buffer = ("" if self.inside else self.buffer), ""
        return re.sub(r"\s+$", "", rest) if rest else ""


def stream_chat(messages: list[dict], model: str) -> Iterator[str]:
    """Yield text tokens from the local Ollama model."""
    import httpx

    payload = {
        "model": model,
        "messages": messages,
        "stream": True,
        "think": False,
        "options": {"temperature": 0.3, "num_predict": int(os.getenv("LOCAL_LLM_MAX_TOKENS", "900"))},
    }
    filt = _ThinkFilter()
    timeout = httpx.Timeout(connect=1.0, read=120.0, write=10.0, pool=5.0)
    with httpx.stream("POST", f"{base_url()}/api/chat", json=payload, timeout=timeout) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            if data.get("error"):
                raise RuntimeError("local model error")
            piece = (data.get("message") or {}).get("content", "")
            text = filt.feed(piece) if piece else ""
            if text:
                yield text
            if data.get("done"):
                break
    tail = filt.flush()
    if tail:
        yield tail
