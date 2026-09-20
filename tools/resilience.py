"""Fault-tolerance helpers shared by every feature that calls the LLM API.

- classify_error: decide whether a failure is worth retrying, needs another model,
  or means the key/config is broken (retrying can never help).
- CircuitBreaker: after repeated failures, stop calling the API for a cool-down so
  users get the built-in fallback instantly instead of waiting for timeouts.
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

NETWORK = "network"  # no route / DNS failure / connection refused: every model on that host will fail too
TRANSIENT = "transient"  # timeout, 429, 5xx: retry, then try another model
AUTH = "auth"  # 401/403: the key is wrong, retrying or switching model cannot help
MODEL = "model"  # 400/404: this model/request is rejected, try a different model
OTHER = "other"


def classify_error(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if status in (401, 403):
        return AUTH
    if status in (400, 404, 422):
        return MODEL
    if status is None:
        if _is_timeout(exc):
            return TRANSIENT
        return NETWORK if _looks_like_network_error(exc) else OTHER
    if status in (408, 409, 425, 429) or status >= 500:
        return TRANSIENT
    return OTHER


def _class_names(exc: Exception) -> set[str]:
    names = {cls.__name__.lower() for cls in type(exc).__mro__}
    cause = exc.__cause__ or exc.__context__
    if cause is not None and cause is not exc:
        names |= {cls.__name__.lower() for cls in type(cause).__mro__}
    return names


def _is_timeout(exc: Exception) -> bool:
    return bool(_class_names(exc) & {"timeouterror", "apitimeouterror", "timeoutexception", "readtimeout", "connecttimeout"})


def _looks_like_network_error(exc: Exception) -> bool:
    return bool(_class_names(exc) & {"connectionerror", "apiconnectionerror", "connecterror", "gaierror", "oserror", "networkerror"})


def offline_mode() -> bool:
    """OFFLINE_MODE=1 forces every cloud call to be skipped, so nothing waits on a dead network."""
    return os.getenv("OFFLINE_MODE", "").strip().lower() in {"1", "true", "yes", "on"}


class CircuitBreaker:
    """Closed -> (N failures) -> open for `cooldown` seconds -> half-open (one trial call)."""

    def __init__(self, threshold: int = 3, cooldown: float = 60.0, clock=time.monotonic) -> None:
        self.threshold = threshold
        self.cooldown = cooldown
        self._clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at: float | None = None
        self._trial_in_flight = False
        self.last_error: str | None = None

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at < self.cooldown:
                return False
            if self._trial_in_flight:
                return False  # only one probe while half-open
            self._trial_in_flight = True
            return True

    def record_success(self) -> None:
        with self._lock:
            if self._opened_at is not None:
                logger.info("LLM circuit closed: service recovered")
            self._failures = 0
            self._opened_at = None
            self._trial_in_flight = False
            self.last_error = None

    def record_failure(self, reason: str = "") -> None:
        with self._lock:
            self._failures += 1
            self.last_error = reason or self.last_error
            self._trial_in_flight = False
            if self._opened_at is not None or self._failures >= self.threshold:
                if self._opened_at is None:
                    logger.error("LLM circuit opened after %d failures: %s", self._failures, reason)
                self._opened_at = self._clock()

    def trip(self, reason: str) -> None:
        """Open immediately (used for permanent errors such as an invalid key)."""
        with self._lock:
            self._failures = max(self._failures, self.threshold)
            self._opened_at = self._clock()
            self._trial_in_flight = False
            self.last_error = reason
            logger.error("LLM circuit tripped: %s", reason)

    def state(self) -> dict:
        with self._lock:
            if self._opened_at is None:
                return {"status": "ok" if self._failures == 0 else "degraded", "retry_in": 0}
            remaining = max(0.0, self.cooldown - (self._clock() - self._opened_at))
            return {"status": "down", "retry_in": round(remaining)}


# One breaker for the whole LLM provider: chat, tutor and scoring share its health.
llm_breaker = CircuitBreaker()


# Gates for optional cloud services that are only used for extras (graph memory).
neo4j_breaker = CircuitBreaker(threshold=1, cooldown=90.0)
