"""Public API for the practice / interview mode. No LLM, no code execution.

- Python and data-science challenges are graded in the learner's browser; the server
  only serves the prompt, starter code and tests.
- Java and Spring Boot challenges are graded here by static pattern checks (comments
  and strings are stripped first so a comment cannot fake a pass) and MCQ answers.
"""
from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque

from tools.challenge_bank import CHALLENGES, LESSON_LINKS, POINTS

TRACKS = ("python", "datascience", "java", "spring")
MAX_SUBMISSION_CHARS = 10_000

_BY_ID = {c["id"]: c for c in CHALLENGES}
_PRIVATE_KEYS = {"solution", "answer", "rubric", "explanation"}
_STRING_OR_COMMENT = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])\'|//[^\n]*|/\*.*?\*/', re.S)


def get(challenge_id: str) -> dict | None:
    return _BY_ID.get(challenge_id)


def public_view(challenge: dict) -> dict:
    """What the browser may see up front: never the answer, solution, rubric or explanation."""
    view = {k: v for k, v in challenge.items() if k not in _PRIVATE_KEYS}
    view["points"] = POINTS[challenge["difficulty"]]
    view["hint_count"] = len(challenge.get("hints", []))
    view["review_lesson"] = LESSON_LINKS[challenge["track"]]
    view["graded"] = "browser" if challenge["type"] == "code" else "server"
    if challenge["type"] == "rubric":
        view["check_count"] = len(challenge["rubric"])
    return view


def list_public(track: str) -> list[dict]:
    order = {"easy": 0, "medium": 1, "hard": 2}
    items = [c for c in CHALLENGES if c["track"] == track]
    return [public_view(c) for c in sorted(items, key=lambda c: (order[c["difficulty"]], c["id"]))]


def _strip(code: str) -> str:
    return _STRING_OR_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n") or " ", code)


def grade_mcq(challenge: dict, choice: int) -> dict:
    correct = challenge["answer"]
    return {
        "passed": choice == correct,
        "correct_index": correct,
        "explanation": challenge["explanation"],
        "points": POINTS[challenge["difficulty"]] if choice == correct else 0,
    }


def grade_rubric(challenge: dict, code: str) -> dict:
    """Static review. Proves structure and common mistakes, never that the code runs."""
    from tools.tutor import lint_java

    stripped = _strip(code)
    checks = []
    for rule in challenge["rubric"]:
        found = re.search(rule["pattern"], stripped) is not None
        ok = found if rule["must"] else not found
        checks.append({
            "id": rule["id"],
            "description": rule["description"],
            "ok": ok,
            "message": "" if ok else rule["fix"],
        })
    passed_count = sum(c["ok"] for c in checks)
    passed = passed_count == len(checks)
    notes = [f for f in lint_java(code, spring=challenge["track"] == "spring") if f["severity"] in {"error", "warning"}]
    return {
        "passed": passed,
        "score": round(passed_count / len(checks), 2),
        "checks": checks,
        "notes": notes,
        "explanation": challenge["explanation"] if passed else None,
        "points": POINTS[challenge["difficulty"]] if passed else 0,
        "static": True,
    }


def solution_view(challenge: dict) -> dict:
    """Revealed only after the learner submits or gives up."""
    return {"explanation": challenge["explanation"], "solution": challenge.get("solution"), "options": challenge.get("options"), "correct_index": challenge.get("answer")}


class RateLimiter:
    """Sliding-window limiter so a busy or abusive client cannot overload a small server."""

    def __init__(self, limit: int = 90, window: float = 60.0, clock=time.monotonic) -> None:
        self.limit, self.window, self._clock = limit, window, clock
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = self._clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            if len(self._hits) > 5000:  # bound memory
                for stale in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window][:1000]:
                    self._hits.pop(stale, None)
            return True


limiter = RateLimiter()
ip_limiter = RateLimiter(limit=90 * 12)  # per shared network; see IP_LIMIT_FACTOR in api/app.py
