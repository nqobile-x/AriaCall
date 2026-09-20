"""Fault-tolerance tests: what happens when the AI API is slow, rate-limited, broken or down."""

import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from tools import resilience, tutor
from tools.resilience import AUTH, MODEL, NETWORK, OTHER, TRANSIENT, CircuitBreaker, classify_error


# Tests must not depend on whether a local Ollama happens to be running on this machine.
os.environ["LOCAL_LLM"] = "off"
os.environ["TUTOR_CACHE"] = "off"  # cache behaviour has its own tests
os.environ["TUTOR_RATE_LIMIT"] = "100000"

HEADERS = {"X-API-Key": "aria-demo-key-2024"}
FIXTURE = Path(__file__).parent / "fixtures" / "dirty_data_test.csv"


class ApiError(Exception):
    def __init__(self, status_code=None, message="boom"):
        super().__init__(message)
        self.status_code = status_code


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class ClassifyTests(unittest.TestCase):
    def test_classification(self):
        self.assertEqual(classify_error(ApiError(429)), TRANSIENT)
        self.assertEqual(classify_error(ApiError(503)), TRANSIENT)
        self.assertEqual(classify_error(ApiError(401)), AUTH)
        self.assertEqual(classify_error(ApiError(403)), AUTH)
        self.assertEqual(classify_error(ApiError(404)), MODEL)
        self.assertEqual(classify_error(ApiError(418)), OTHER)
        self.assertEqual(classify_error(ConnectionError("down")), NETWORK)
        self.assertEqual(classify_error(TimeoutError()), TRANSIENT)
        self.assertEqual(classify_error(ValueError("bug")), OTHER)


class BreakerTests(unittest.TestCase):
    def test_opens_after_threshold_and_recovers(self):
        clock = FakeClock()
        breaker = CircuitBreaker(threshold=3, cooldown=60, clock=clock)
        for _ in range(2):
            breaker.record_failure("x")
        self.assertTrue(breaker.allow())
        self.assertEqual(breaker.state()["status"], "degraded")
        breaker.record_failure("x")
        self.assertFalse(breaker.allow())
        self.assertEqual(breaker.state()["status"], "down")
        clock.now += 61
        self.assertTrue(breaker.allow())  # half-open: exactly one probe
        self.assertFalse(breaker.allow())
        breaker.record_success()
        self.assertTrue(breaker.allow())
        self.assertEqual(breaker.state()["status"], "ok")

    def test_failed_probe_reopens(self):
        clock = FakeClock()
        breaker = CircuitBreaker(threshold=1, cooldown=30, clock=clock)
        breaker.record_failure("x")
        clock.now += 31
        self.assertTrue(breaker.allow())
        breaker.record_failure("still down")
        self.assertFalse(breaker.allow())

    def test_trip_opens_immediately(self):
        breaker = CircuitBreaker(threshold=5, cooldown=60)
        breaker.trip("bad key")
        self.assertFalse(breaker.allow())


def _events(fn_or_iter, *, env="key", mode="explain", language="python", code="def f(x=[]):\n    pass\n"):
    lesson = tutor.get_lesson("python-3", "python") if mode == "teach" else None
    findings = tutor.lint_code(code, language) if code else []
    messages = tutor.build_messages(language=language, level="beginner", mode=mode, code=code, lesson=lesson, findings=findings)

    def offline():
        return tutor.offline_for(language=language, level="beginner", mode=mode, code=code, lesson=lesson, findings=findings, context="")

    with patch.dict("os.environ", {"GROQ_API_KEY": env}), patch("tools.resilience.llm_breaker", CircuitBreaker()), patch("tools.tutor._sleep"):
        with patch("tools.tutor.stream_tutor", fn_or_iter):
            return list(tutor.tutor_events(messages, offline))


def _text(events):
    return "".join(e["text"] for e in events if e["type"] == "token")


class TutorFailoverTests(unittest.TestCase):
    def test_happy_path_uses_primary_model_once(self):
        calls = []

        def ok(messages, model=None):
            calls.append(model)
            yield "hello"

        events = _events(ok)
        self.assertEqual(_text(events), "hello")
        self.assertEqual(calls, [tutor.model_chain()[0]])
        self.assertFalse([e for e in events if e["type"] == "notice"])

    def test_transient_error_is_retried_on_same_model(self):
        calls = []

        def flaky(messages, model=None):
            calls.append(model)
            if len(calls) == 1:
                raise ApiError(429)
            yield "recovered"

        self.assertEqual(_text(_events(flaky)), "recovered")
        self.assertEqual(calls[0], calls[1])

    def test_falls_back_to_next_model(self):
        calls = []

        def primary_down(messages, model=None):
            calls.append(model)
            if model == tutor.model_chain()[0]:
                raise ApiError(503)
            yield "from fallback"

        events = _events(primary_down)
        self.assertEqual(_text(events), "from fallback")
        self.assertIn(tutor.model_chain()[1], calls)

    def test_bad_model_skips_retry(self):
        calls = []

        def rejected(messages, model=None):
            calls.append(model)
            if model == tutor.model_chain()[0]:
                raise ApiError(404, "model not found")
            yield "ok"

        self.assertEqual(_text(_events(rejected)), "ok")
        self.assertEqual(calls.count(tutor.model_chain()[0]), 1)

    def test_bad_key_goes_straight_to_offline_without_trying_other_models(self):
        calls = []

        def unauthorised(messages, model=None):
            calls.append(model)
            raise ApiError(401, "Invalid API Key")
            yield  # pragma: no cover

        events = _events(unauthorised)
        self.assertEqual(len(calls), 1)
        self.assertIn("Offline mode", _text(events))
        self.assertTrue([e for e in events if e["type"] == "notice"])

    def test_total_outage_returns_offline_guidance_with_findings(self):
        def down(messages, model=None):
            raise ConnectionError("network unreachable")
            yield  # pragma: no cover

        text = _text(_events(down))
        self.assertIn("Offline mode", text)
        self.assertIn("mutable default", text)  # the automated checks still ran

    def test_never_leaks_provider_error_details(self):
        def down(messages, model=None):
            raise ApiError(500, "secret gsk_abc123 internal path C:\\srv")
            yield  # pragma: no cover

        events = _events(down)
        self.assertNotIn("gsk_abc123", json.dumps(events))

    def test_mid_stream_drop_keeps_partial_answer_and_warns(self):
        def drops(messages, model=None):
            yield "partial "
            raise ConnectionError("reset")

        events = _events(drops)
        self.assertEqual(_text(events), "partial ")
        self.assertTrue([e for e in events if e["type"] == "notice" and "incomplete" in e["text"]])

    def test_missing_key_uses_offline_without_calling_api(self):
        called = []

        def should_not_run(messages, model=None):
            called.append(1)
            yield "x"

        with patch.dict("os.environ", {"GROQ_API_KEY": ""}):
            events = _events(should_not_run, env="")
        self.assertEqual(called, [])
        self.assertIn("Offline mode", _text(events))

    def test_circuit_opens_then_skips_the_api_entirely(self):
        breaker = CircuitBreaker(threshold=2, cooldown=60)
        calls = []

        def down(messages, model=None):
            calls.append(model)
            raise ApiError(503)
            yield  # pragma: no cover

        messages = tutor.build_messages(language="python", level="beginner", mode="explain", code="x = 1")
        with patch.dict("os.environ", {"GROQ_API_KEY": "k"}), patch("tools.resilience.llm_breaker", breaker), patch("tools.tutor._sleep"), patch("tools.tutor.stream_tutor", down):
            for _ in range(2):
                list(tutor.tutor_events(messages, lambda: "offline"))
            used = len(calls)
            events = list(tutor.tutor_events(messages, lambda: "offline"))
        self.assertEqual(len(calls), used)  # third request never touched the API
        self.assertEqual(_text(events), "offline")


class OfflineTutorTests(unittest.TestCase):
    def test_every_track_and_mode_produces_useful_guidance(self):
        for language in tutor.LANGUAGES:
            lesson = tutor.lessons_for(language)[0]
            full = tutor.get_lesson(lesson["id"], language)
            for mode in ("explain", "review", "teach"):
                text = tutor.offline_for(
                    language=language, level="beginner", mode=mode, code="class A {}" if language in {"java", "spring"} else "x = 1\n",
                    lesson=full if mode == "teach" else None, findings=[], context="",
                )
                self.assertIn("Offline mode", text)
                self.assertIn("http", text, f"{language}/{mode} should point to docs")

    def test_teach_includes_starter_todos_and_lints_the_starter(self):
        lesson = tutor.get_lesson("ds-8", "datascience")
        text = tutor.offline_for(language="datascience", level="beginner", mode="teach", code="", lesson=lesson, findings=[], context="")
        self.assertIn("StandardScaler", text)
        self.assertIn("leakage", text)

    def test_analyse_uses_the_dataset_summary(self):
        context = "Rows: 40\nColumns: 2\n\nColumns:\n- age: integer, 3 missing, 28 distinct\n\nDetected quality issues:\n- Duplicate records (removed): 4"
        text = tutor.offline_for(language="datascience", level="beginner", mode="analyse", code="", lesson=None, findings=[], context=context)
        self.assertIn("age: integer", text)
        self.assertIn("Duplicate records", text)
        self.assertIn("Clean & download", text)

    def test_explain_reads_structure_without_ai(self):
        text = tutor.offline_for(language="python", level="beginner", mode="explain", code="import os\n\ndef add(a, b):\n    return a + b\n", lesson=None, findings=[], context="")
        self.assertIn("add(a, b)", text)
        self.assertIn("os", text)
        java = tutor.offline_for(language="spring", level="beginner", mode="explain", code="@RestController\npublic class Hello {\n  public String hi() { return \"x\"; }\n}\n", lesson=None, findings=[], context="")
        self.assertIn("Hello", java)


class EndToEndOutageTests(unittest.TestCase):
    """The whole product with the AI provider completely down."""

    def setUp(self):
        self.client = TestClient(app)

    def test_tutor_endpoint_degrades_gracefully(self):
        def down(messages, model=None):
            raise ConnectionError("no route to host")
            yield  # pragma: no cover

        with patch.dict("os.environ", {"GROQ_API_KEY": "k"}), patch("tools.resilience.llm_breaker", CircuitBreaker()), patch("tools.tutor._sleep"), patch("tools.tutor.stream_tutor", down):
            r = self.client.post("/tutor/stream", json={"language": "spring", "mode": "review", "code": "@Autowired\nprivate R r;\n"}, headers=HEADERS)
        self.assertEqual(r.status_code, 200)
        events = [json.loads(x[6:]) for x in r.text.split("\n\n") if x.startswith("data: ")]
        kinds = [e["type"] for e in events]
        self.assertEqual(kinds[0], "lint")
        self.assertIn("notice", kinds)
        self.assertEqual(kinds[-1], "done")
        self.assertNotIn("error", kinds)
        self.assertIn("constructor injection", "".join(e.get("text", "") for e in events))

    def test_data_cleaning_needs_no_ai_at_all(self):
        with patch.dict("os.environ", {"GROQ_API_KEY": ""}), FIXTURE.open("rb") as fh:
            r = self.client.post("/data/clean?mode=report", files={"file": ("dirty.csv", fh, "text/csv")})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["rows_after"], 36)
            fh.seek(0)
            self.assertEqual(self.client.post("/data/profile", files={"file": ("dirty.csv", fh, "text/csv")}).status_code, 200)

    def test_health_reports_the_circuit(self):
        breaker = CircuitBreaker(threshold=1, cooldown=60)
        breaker.trip("bad key")
        with patch.dict("os.environ", {"GROQ_API_KEY": "k"}), patch("tools.resilience.llm_breaker", breaker):
            body = self.client.get("/health").json()
        self.assertEqual(body["status"], "ok")  # the service itself is up
        self.assertEqual(body["llm_circuit"]["status"], "down")
        self.assertIn("unavailable", body["llm"])

    def test_support_answers_from_kb_when_the_model_is_down_and_stops_calling_it(self):
        from tools.support_tools import draft_response

        state = {"customer": {"name": "Thabo"}, "faq_sources": [{"title": "Password Reset", "text": "Use the reset link."}], "message": "reset password"}
        breaker = CircuitBreaker(threshold=2, cooldown=60)
        attempts = []

        def failing_groq(*args, **kwargs):
            attempts.append(1)
            raise ConnectionError("down")

        with patch("tools.resilience.llm_breaker", breaker), patch("groq.Groq", failing_groq):
            replies = [draft_response(state, use_groq=True) for _ in range(4)]
        self.assertTrue(all("Use the reset link." in r for r in replies))
        self.assertEqual(len(attempts), 2)  # after two failures the model is skipped


if __name__ == "__main__":
    unittest.main()
