"""Keeps the API and a small Render instance calm: caching, rate limits and load shedding."""

import json
import os
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ["LOCAL_LLM"] = "off"
os.environ["TUTOR_CACHE"] = "off"
os.environ["TUTOR_RATE_LIMIT"] = "100000"

from main import app  # noqa: E402
from tools import tutor  # noqa: E402
from tools.resilience import CircuitBreaker  # noqa: E402
from tools.tutor_cache import ResponseCache  # noqa: E402

HEADERS = {"X-API-Key": "aria-demo-key-2024"}
LONG = "This is a complete answer that is long enough to be worth caching for later."


def events_of(response):
    return [json.loads(line[6:]) for line in response.text.split("\n\n") if line.startswith("data: ")]


def text_of(events):
    return "".join(e.get("text", "") for e in events if e["type"] == "token")


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class CacheUnitTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict("os.environ", {"TUTOR_CACHE": "on"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_hit_miss_and_stats(self):
        c = ResponseCache()
        self.assertIsNone(c.get("k"))
        c.set("k", LONG)
        self.assertEqual(c.get("k"), LONG)
        self.assertEqual(c.stats(), {"entries": 1, "hits": 1, "misses": 1, "hit_rate": 0.5})

    def test_expires(self):
        clock = FakeClock()
        c = ResponseCache(ttl=10, clock=clock)
        c.set("k", LONG)
        clock.now = 11
        self.assertIsNone(c.get("k"))

    def test_bounded_and_least_recently_used_goes_first(self):
        c = ResponseCache(max_entries=2)
        c.set("a", LONG)
        c.set("b", LONG)
        c.get("a")
        c.set("c", LONG)
        self.assertIsNotNone(c.get("a"))
        self.assertIsNone(c.get("b"))
        self.assertEqual(c.stats()["entries"], 2)

    def test_refuses_tiny_or_huge_answers(self):
        c = ResponseCache()
        c.set("tiny", "ok")
        c.set("huge", "x" * 30_000)
        self.assertIsNone(c.get("tiny"))
        self.assertIsNone(c.get("huge"))

    def test_key_depends_on_the_whole_prompt(self):
        base = [{"role": "user", "content": "explain this code"}]
        self.assertEqual(ResponseCache.key(base), ResponseCache.key(list(base)))
        self.assertNotEqual(ResponseCache.key(base), ResponseCache.key([{"role": "user", "content": "explain that code"}]))

    def test_can_be_switched_off(self):
        c = ResponseCache()
        with patch.dict("os.environ", {"TUTOR_CACHE": "off"}):
            c.set("k", LONG)
            self.assertIsNone(c.get("k"))


class CachedTutorTests(unittest.TestCase):
    """A repeated question must not reach the model again."""

    def setUp(self):
        for patcher in (
            patch.dict("os.environ", {"TUTOR_CACHE": "on", "GROQ_API_KEY": "k", "LOCAL_LLM": "off"}),
            patch("tools.tutor.answer_cache", ResponseCache()),
            patch("tools.resilience.llm_breaker", CircuitBreaker()),
            patch("tools.tutor._sleep"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.messages = tutor.build_messages(language="python", level="beginner", mode="explain", code="print(1)")

    def run_events(self, stream):
        with patch("tools.tutor.stream_tutor", stream):
            return list(tutor.tutor_events(self.messages, lambda: "OFFLINE"))

    def test_second_identical_request_never_calls_the_model(self):
        calls = []

        def model(messages, model=None):
            calls.append(1)
            yield LONG

        first = self.run_events(model)
        second = self.run_events(model)
        self.assertEqual(text_of(first), LONG)
        self.assertEqual(text_of(second), LONG)
        self.assertEqual(len(calls), 1)

    def test_cached_answers_still_work_when_the_model_is_down(self):
        def model(messages, model=None):
            yield LONG

        def down(messages, model=None):
            raise ConnectionError("no route")
            yield  # pragma: no cover

        self.run_events(model)
        self.assertEqual(text_of(self.run_events(down)), LONG)

    def test_failures_and_offline_guidance_are_never_cached(self):
        def down(messages, model=None):
            raise ConnectionError("no route")
            yield  # pragma: no cover

        def model(messages, model=None):
            yield LONG

        self.assertIn("OFFLINE", text_of(self.run_events(down)))
        self.assertEqual(text_of(self.run_events(model)), LONG)  # the failure was not remembered

    def test_partial_streams_are_not_cached(self):
        def drops(messages, model=None):
            yield "a half sentence that stops"
            raise ConnectionError("reset")

        def model(messages, model=None):
            yield LONG

        self.run_events(drops)
        self.assertEqual(text_of(self.run_events(model)), LONG)

    def test_different_code_gets_a_different_answer(self):
        def model_a(messages, model=None):
            yield LONG

        def model_b(messages, model=None):
            yield "A different explanation that is also long enough to be cached properly."

        self.run_events(model_a)
        self.messages = tutor.build_messages(language="python", level="beginner", mode="explain", code="print(2)")
        self.assertIn("different explanation", text_of(self.run_events(model_b)))


class EndpointProtectionTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        for patcher in (
            patch.dict("os.environ", {"GROQ_API_KEY": "k", "LOCAL_LLM": "off", "TUTOR_CACHE": "off"}),
            patch("tools.resilience.llm_breaker", CircuitBreaker()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def post(self, body=None):
        body = body or {"language": "python", "mode": "explain", "code": "print(1)"}
        return self.client.post("/tutor/stream", json=body, headers=HEADERS)

    def test_rate_limit_returns_a_friendly_429(self):
        import api.app as app_module

        app_module._tutor_limiter._hits.clear()
        with patch.dict("os.environ", {"TUTOR_RATE_LIMIT": "3"}), patch("tools.tutor.stream_tutor", return_value=iter([LONG])):
            codes = [self.post().status_code for _ in range(5)]
        app_module._tutor_limiter._hits.clear()
        self.assertEqual(codes[:3], [200, 200, 200])
        self.assertEqual(codes[3:], [429, 429])

    def test_rate_limit_message_is_readable(self):
        import api.app as app_module

        app_module._tutor_limiter._hits.clear()
        with patch.dict("os.environ", {"TUTOR_RATE_LIMIT": "1"}), patch("tools.tutor.stream_tutor", return_value=iter([LONG])):
            self.post()
            detail = self.post().json()["detail"]
        app_module._tutor_limiter._hits.clear()
        self.assertIn("wait a minute", detail)

    def test_busy_server_sheds_load_with_built_in_guidance_instead_of_queueing(self):
        import api.app as app_module

        started = time.monotonic()
        held = [app_module._TUTOR_SLOTS.acquire() for _ in range(4)]  # every model slot busy
        try:
            response = self.post()
        finally:
            for _ in held:
                app_module._TUTOR_SLOTS.release()
        elapsed = time.monotonic() - started
        events = events_of(response)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[-1]["type"], "done")
        self.assertIn("very busy", " ".join(e["text"] for e in events if e["type"] == "notice"))
        self.assertIn("Offline mode", text_of(events))
        self.assertLess(elapsed, 3.0, "a busy server must answer quickly, not queue")

    def test_slots_are_released_after_every_request_even_on_failure(self):
        import api.app as app_module

        def boom(messages, model=None):
            raise RuntimeError("model exploded")
            yield  # pragma: no cover

        with patch("tools.tutor.stream_tutor", boom), patch("tools.tutor._sleep"):
            for _ in range(10):
                self.post()
        # if a slot had leaked, this would time out after the queue wait
        acquired = [app_module._TUTOR_SLOTS.acquire(timeout=0.1) for _ in range(4)]
        for ok in acquired:
            if ok:
                app_module._TUTOR_SLOTS.release()
        self.assertTrue(all(acquired), "a concurrency slot leaked")

    def test_concurrent_learners_are_all_served_and_slots_stay_bounded(self):
        import api.app as app_module

        active = {"now": 0, "max": 0}
        lock = threading.Lock()

        def slow_model(messages, model=None):
            with lock:
                active["now"] += 1
                active["max"] = max(active["max"], active["now"])
            try:
                time.sleep(0.15)
                yield "A reasonably long answer that streams slowly for the concurrency test."
            finally:
                with lock:
                    active["now"] -= 1

        results = []

        def learner(i):
            client = TestClient(app)
            r = client.post("/tutor/stream", json={"language": "python", "mode": "explain", "code": f"print({i})"}, headers=HEADERS)
            events = events_of(r)
            results.append((r.status_code, events[-1]["type"], text_of(events)))

        with patch("tools.tutor.stream_tutor", slow_model):
            threads = [threading.Thread(target=learner, args=(i,)) for i in range(12)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
        self.assertEqual(len(results), 12)
        self.assertTrue(all(code == 200 and last == "done" and text for code, last, text in results))
        self.assertLessEqual(active["max"], 4, "more model calls ran at once than the slot limit allows")


class SingleFlightAndSlotTests(unittest.TestCase):
    """A class opening the same lesson must cost one model call, and cache hits must never queue."""

    def setUp(self):
        for patcher in (
            patch.dict("os.environ", {"TUTOR_CACHE": "on", "GROQ_API_KEY": "k", "LOCAL_LLM": "off"}),
            patch("tools.tutor.answer_cache", ResponseCache()),
            patch("tools.resilience.llm_breaker", CircuitBreaker()),
            patch("tools.tutor._sleep"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.messages = tutor.build_messages(language="python", level="beginner", mode="explain", code="print('same lesson')")

    def collect(self, slots):
        return list(tutor.tutor_events(self.messages, lambda: "OFFLINE", slots=slots, slot_wait=0.2))

    def test_many_identical_requests_make_one_model_call(self):
        calls = []

        def slow(messages, model=None):
            calls.append(1)
            time.sleep(0.4)
            yield LONG

        results = []
        slots = threading.BoundedSemaphore(1)  # a single model slot: followers must not need one
        with patch("tools.tutor.stream_tutor", slow):
            threads = [threading.Thread(target=lambda: results.append(text_of(self.collect(slots)))) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)
        self.assertEqual(len(calls), 1, "identical in-flight questions must share one model call")
        self.assertEqual(results, [LONG] * 8)

    def test_followers_never_hold_a_model_slot_while_waiting(self):
        slots = threading.BoundedSemaphore(1)
        started, release = threading.Event(), threading.Event()

        def gated(messages, model=None):
            started.set()
            release.wait(5)
            yield LONG

        outcomes = []
        with patch("tools.tutor.stream_tutor", gated):
            leader = threading.Thread(target=lambda: outcomes.append(text_of(self.collect(slots))))
            leader.start()
            started.wait(5)
            follower = threading.Thread(target=lambda: outcomes.append(text_of(self.collect(slots))))
            follower.start()
            time.sleep(0.3)
            # the leader holds the only slot; the follower is waiting for the answer, not shed
            self.assertTrue(follower.is_alive(), "the follower should wait for the leader's answer")
            release.set()
            leader.join(5)
            follower.join(5)
        self.assertEqual(outcomes, [LONG, LONG])

    def test_cache_hits_are_served_even_when_every_slot_is_busy(self):
        def model(messages, model=None):
            yield LONG

        with patch("tools.tutor.stream_tutor", model):
            self.collect(None)  # warm the cache
        slots = threading.BoundedSemaphore(1)
        slots.acquire()  # the only slot is taken
        events = self.collect(slots)
        self.assertEqual(text_of(events), LONG)
        self.assertFalse([e for e in events if e["type"] == "notice"], "a cache hit must not be shed")

    def test_a_failed_leader_does_not_strand_followers(self):
        calls = []

        def flaky(messages, model=None):
            calls.append(1)
            if len(calls) == 1:
                time.sleep(0.2)
                raise ConnectionError("no route")
            yield LONG

        results = []
        with patch("tools.tutor.stream_tutor", flaky):
            threads = [threading.Thread(target=lambda: results.append(text_of(self.collect(None)))) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)
        self.assertEqual(len(results), 3, "every learner must get an answer even if the leader failed")
        self.assertTrue(all(r for r in results))


class ClassroomRateLimitTests(unittest.TestCase):
    """Learners behind one school IP must not be throttled as if they were one person."""

    def setUp(self):
        from tools import challenges

        self.challenges = challenges
        self.client = TestClient(app)
        challenges.limiter._hits.clear()
        challenges.ip_limiter._hits.clear()
        self.addCleanup(challenges.limiter._hits.clear)
        self.addCleanup(challenges.ip_limiter._hits.clear)
        self.old_limit = challenges.limiter.limit
        self.addCleanup(setattr, challenges.limiter, "limit", self.old_limit)

    def check(self, client_id=None):
        headers = dict(HEADERS)
        if client_id:
            headers["X-Client-Id"] = client_id
        return self.client.post("/challenges/check", json={"id": "sp-1", "choice": 0}, headers=headers).status_code

    def test_each_browser_gets_its_own_allowance_on_a_shared_ip(self):
        self.challenges.limiter.limit = 3
        a = [self.check("learner-a") for _ in range(5)]
        b = [self.check("learner-b") for _ in range(3)]
        self.assertEqual(a, [200, 200, 200, 429, 429])
        self.assertEqual(b, [200, 200, 200], "learner B must not pay for learner A's requests")

    def test_rotating_ids_cannot_bypass_the_network_cap(self):
        self.challenges.limiter.limit = 1  # per-network cap becomes 12
        codes = [self.check(f"fresh-id-{i}") for i in range(15)]
        self.assertEqual(codes[:12], [200] * 12)
        self.assertEqual(codes[12:], [429] * 3)

    def test_client_id_is_sanitised_and_optional(self):
        self.assertEqual(self.check("x" * 500), 200)
        self.assertEqual(self.check("<script>alert(1)</script>"), 200)
        self.assertEqual(self.check(None), 200)

    def test_frontend_sends_the_client_id_on_same_origin_requests_only(self):
        source = TestClient(app).get("/static/app.js").text
        self.assertIn("X-Client-Id", source)
        self.assertIn("url.startsWith('/') || url.startsWith(location.origin)", source)


class VoiceCostsNothingOnTheServerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_voice_script_is_static_and_never_calls_the_server(self):
        source = self.client.get("/static/voice.js").text
        self.assertEqual(self.client.get("/static/voice.js").status_code, 200)
        for banned in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon"):
            self.assertNotIn(banned, source, f"voice.js must stay client-side ({banned})")

    def test_voice_uses_browser_speech_apis_only(self):
        source = self.client.get("/static/voice.js").text
        self.assertIn("speechSynthesis", source)
        self.assertIn("SpeechRecognition", source)

    def test_spoken_questions_reuse_the_same_rate_limited_endpoint(self):
        source = self.client.get("/static/app.js").text
        self.assertIn("/tutor/stream", source)
        for path in ("/voice/ask", "/tutor/voice", "/transcribe"):
            self.assertNotIn(path, self.client.get("/static/practice.js").text)


if __name__ == "__main__":
    unittest.main()
