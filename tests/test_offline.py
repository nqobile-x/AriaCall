"""Offline capability: what still works with no internet, and how fast it fails."""

import importlib.util
import json
import os
import socket
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from main import app
from tools import local_llm, tutor
from tools.local_llm import _ThinkFilter
from tools.resilience import NETWORK, TRANSIENT, CircuitBreaker, classify_error, offline_mode

os.environ["LOCAL_LLM"] = "off"
os.environ["TUTOR_CACHE"] = "off"  # cache behaviour has its own tests
os.environ["TUTOR_RATE_LIMIT"] = "100000"  # individual tests switch it on explicitly

HEADERS = {"X-API-Key": "aria-demo-key-2024"}
ROOT = Path(__file__).parent.parent
VOICE_READY = (ROOT / "voice" / "models" / "kokoro-v1.0.onnx").exists() and (ROOT / "voice" / "models" / "voices-v1.0.bin").exists()

_spec = importlib.util.spec_from_file_location("fetch_offline_assets", ROOT / "scripts" / "fetch_offline_assets.py")
fetch_assets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch_assets)


def _dead_network(messages, model=None):
    raise ConnectionError("no route to host")
    yield  # pragma: no cover


@contextmanager
def tutor_env(**env):
    base = {"GROQ_API_KEY": "key"}
    base.update(env)
    sleeps = MagicMock()
    with patch.dict("os.environ", base), patch("tools.resilience.llm_breaker", CircuitBreaker()), patch("tools.tutor._sleep", sleeps):
        yield sleeps


def run_tutor(stream, code="def f(x=[]):\n    pass\n"):
    findings = tutor.lint_code(code, "python")
    messages = tutor.build_messages(language="python", level="beginner", mode="review", code=code, findings=findings)
    offline = lambda: tutor.offline_for(language="python", level="beginner", mode="review", code=code, lesson=None, findings=findings, context="")
    with patch("tools.tutor.stream_tutor", stream):
        return list(tutor.tutor_events(messages, offline))


def text(events):
    return "".join(e["text"] for e in events if e["type"] == "token")


def notices(events):
    return [e["text"] for e in events if e["type"] == "notice"]


class NetworkClassificationTests(unittest.TestCase):
    def test_dead_network_is_not_retried_like_a_hiccup(self):
        self.assertEqual(classify_error(ConnectionError("x")), NETWORK)
        self.assertEqual(classify_error(socket.gaierror(11001, "getaddrinfo failed")), NETWORK)
        self.assertEqual(classify_error(OSError(101, "Network is unreachable")), NETWORK)
        self.assertEqual(classify_error(TimeoutError()), TRANSIENT)

    def test_wrapped_causes_are_seen(self):
        try:
            try:
                raise socket.gaierror(11001, "getaddrinfo failed")
            except socket.gaierror as inner:
                raise RuntimeError("wrapper without a useful type") from inner
        except RuntimeError as exc:
            self.assertEqual(classify_error(exc), NETWORK)

    def test_offline_mode_flag(self):
        for value in ("1", "true", "YES", "on"):
            with patch.dict("os.environ", {"OFFLINE_MODE": value}):
                self.assertTrue(offline_mode(), value)
        for value in ("", "0", "false"):
            with patch.dict("os.environ", {"OFFLINE_MODE": value}):
                self.assertFalse(offline_mode(), value)


class FastFailTests(unittest.TestCase):
    def test_dead_network_tries_one_model_and_never_sleeps(self):
        calls = []

        def down(messages, model=None):
            calls.append(model)
            raise ConnectionError("no route")
            yield  # pragma: no cover

        with tutor_env() as sleeps:
            events = run_tutor(down)
        self.assertEqual(len(calls), 1, "models on the same dead host must not be tried one by one")
        sleeps.assert_not_called()
        self.assertIn("Offline mode", text(events))
        self.assertTrue(any("internet" in n for n in notices(events)))

    def test_rate_limits_still_use_fallback_models(self):
        calls = []

        def limited(messages, model=None):
            calls.append(model)
            if len(calls) < 3:
                raise type("RateLimitError", (Exception,), {"status_code": 429})()
            yield "ok"

        with tutor_env():
            self.assertEqual(text(run_tutor(limited)), "ok")
        self.assertGreaterEqual(len(calls), 3)


class LocalAiTests(unittest.TestCase):
    def test_local_model_answers_when_the_internet_is_down(self):
        with tutor_env(LOCAL_LLM="on"), patch("tools.local_llm.available_model", return_value="qwen3:0.6b"), \
                patch("tools.local_llm.stream_chat", return_value=iter(["local ", "answer"])):
            events = run_tutor(_dead_network)
        self.assertEqual(text(events), "local answer")
        self.assertNotIn("Offline mode", text(events))
        self.assertTrue(any("local AI model (qwen3:0.6b)" in n for n in notices(events)))

    def test_broken_local_model_falls_back_to_built_in_guidance(self):
        def broken(messages, model):
            raise RuntimeError("model crashed")
            yield  # pragma: no cover

        with tutor_env(), patch("tools.local_llm.available_model", return_value="qwen3:0.6b"), patch("tools.local_llm.stream_chat", broken):
            events = run_tutor(_dead_network)
        self.assertIn("Offline mode", text(events))
        self.assertIn("mutable default", text(events))

    def test_partial_local_answer_is_kept_and_flagged(self):
        def partial(messages, model):
            yield "half "
            raise RuntimeError("stopped")

        with tutor_env(), patch("tools.local_llm.available_model", return_value="m"), patch("tools.local_llm.stream_chat", partial):
            events = run_tutor(_dead_network)
        self.assertEqual(text(events), "half ")
        self.assertTrue(any("incomplete" in n for n in notices(events)))

    def test_offline_mode_never_touches_the_cloud(self):
        called = []

        def cloud(messages, model=None):
            called.append(1)
            yield "cloud"

        with tutor_env(OFFLINE_MODE="1"):
            events = run_tutor(cloud)
        self.assertEqual(called, [])
        self.assertIn("Offline mode", text(events))
        self.assertTrue(any("Offline mode is on" in n for n in notices(events)))


class LocalLlmModuleTests(unittest.TestCase):
    def setUp(self):
        local_llm.reset_cache()
        self.addCleanup(local_llm.reset_cache)

    def _tags(self, names):
        response = MagicMock()
        response.json.return_value = {"models": [{"name": n} for n in names]}
        return response

    def test_detects_first_chat_model_and_skips_embedding_models(self):
        with patch.dict("os.environ", {"LOCAL_LLM": "on", "OLLAMA_MODEL": ""}), patch("httpx.get", return_value=self._tags(["nomic-embed-text", "qwen3:0.6b"])):
            self.assertEqual(local_llm.available_model(force=True), "qwen3:0.6b")

    def test_honours_a_requested_model_only_if_installed(self):
        with patch.dict("os.environ", {"LOCAL_LLM": "on", "OLLAMA_MODEL": "llama3.2:3b"}), patch("httpx.get", return_value=self._tags(["qwen3:0.6b"])):
            self.assertIsNone(local_llm.available_model(force=True))
        with patch.dict("os.environ", {"LOCAL_LLM": "on", "OLLAMA_MODEL": "qwen3:0.6b"}), patch("httpx.get", return_value=self._tags(["qwen3:0.6b"])):
            self.assertEqual(local_llm.available_model(force=True), "qwen3:0.6b")

    def test_not_running_means_none_and_the_result_is_cached(self):
        with patch.dict("os.environ", {"LOCAL_LLM": "on"}), patch("httpx.get", side_effect=ConnectionError("refused")) as get:
            self.assertIsNone(local_llm.available_model(force=True))
            self.assertIsNone(local_llm.available_model())
            self.assertEqual(get.call_count, 1, "the probe result must be cached so requests stay fast")

    def test_can_be_switched_off(self):
        with patch.dict("os.environ", {"LOCAL_LLM": "off"}), patch("httpx.get") as get:
            self.assertIsNone(local_llm.available_model(force=True))
            get.assert_not_called()

    def test_think_filter_removes_reasoning_across_chunk_boundaries(self):
        f = _ThinkFilter()
        pieces = ["Hello <th", "ink>secret reason", "ing</thi", "nk> world", "!"]
        out = "".join(f.feed(p) for p in pieces) + f.flush()
        self.assertEqual(out.replace("  ", " "), "Hello  world!".replace("  ", " "))
        self.assertNotIn("secret", out)

    def test_think_filter_does_not_swallow_ordinary_angle_brackets(self):
        f = _ThinkFilter()
        out = f.feed("List<String> a < b") + f.flush()
        self.assertEqual(out, "List<String> a < b")

    def test_stream_chat_parses_ndjson(self):
        lines = [
            json.dumps({"message": {"content": "Hel"}, "done": False}),
            json.dumps({"message": {"content": "lo"}, "done": False}),
            json.dumps({"message": {"content": ""}, "done": True}),
        ]
        response = MagicMock()
        response.iter_lines.return_value = iter(lines)
        manager = MagicMock()
        manager.__enter__.return_value = response
        with patch("httpx.stream", return_value=manager) as stream:
            self.assertEqual("".join(local_llm.stream_chat([{"role": "user", "content": "hi"}], "qwen3:0.6b")), "Hello")
        payload = stream.call_args.kwargs["json"]
        self.assertFalse(payload["think"])
        self.assertTrue(payload["stream"])
        self.assertEqual(payload["model"], "qwen3:0.6b")

    def test_default_url_is_loopback_only(self):
        with patch.dict("os.environ", {"LOCAL_LLM_URL": ""}):
            self.assertIn("127.0.0.1", local_llm.base_url().replace("localhost", "127.0.0.1"))


class OfflineTouchpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_health_reports_offline_mode_and_local_ai(self):
        with patch.dict("os.environ", {"OFFLINE_MODE": "1", "GROQ_API_KEY": "k"}), patch("tools.local_llm.available_model", return_value="qwen3:0.6b"):
            body = self.client.get("/health").json()
        self.assertEqual(body["mode"], "offline")
        self.assertEqual(body["local_ai"], "qwen3:0.6b")
        self.assertEqual(body["llm"], "local fallback")

    def test_support_wording_never_calls_the_cloud_in_offline_mode(self):
        from tools.support_tools import draft_response

        state = {"customer": {"name": "Thabo"}, "faq_sources": [{"title": "Password Reset", "text": "Use the reset link."}], "message": "reset"}
        with patch.dict("os.environ", {"OFFLINE_MODE": "1"}), patch("groq.Groq", side_effect=AssertionError("cloud was called")):
            self.assertIn("Use the reset link.", draft_response(state, use_groq=True))

    def test_ticket_email_is_skipped_instantly_when_offline(self):
        from api.email_sender import send_ticket_email

        env = {"OFFLINE_MODE": "1", "GMAIL_USER": "a@b.c", "GMAIL_CLIENT_ID": "x", "GMAIL_CLIENT_SECRET": "y", "GMAIL_REFRESH_TOKEN": "z"}
        with patch.dict("os.environ", env), patch("httpx.post", side_effect=AssertionError("network used")):
            self.assertFalse(send_ticket_email("t@x.com", "T", "ARIA-1", "issue"))

    def test_quality_scoring_is_skipped_when_offline(self):
        import asyncio

        from tools.jev_scorer import score_response

        with patch.dict("os.environ", {"OFFLINE_MODE": "1", "JEV_API_KEY": "k"}), patch("httpx.AsyncClient", side_effect=AssertionError("network used")):
            result = asyncio.run(score_response("q", "a"))
        self.assertIsInstance(result, dict)

    def test_neo4j_failure_is_remembered_instead_of_retried_every_request(self):
        from tools import graph_memory

        env = {"NEO4J_URI": "neo4j+s://x", "NEO4J_USERNAME": "u", "NEO4J_PASSWORD": "p"}
        fake_driver = MagicMock()
        fake_driver.verify_connectivity.side_effect = OSError("unreachable")
        with patch.dict("os.environ", env), patch("tools.resilience.neo4j_breaker", CircuitBreaker(threshold=1, cooldown=60)), \
                patch("neo4j.GraphDatabase.driver", return_value=fake_driver) as make:
            graph_memory._driver = None
            for _ in range(5):
                self.assertIsNone(graph_memory._get_driver())
        self.assertEqual(make.call_count, 1, "an offline machine must not pay a connection timeout on every request")

    def test_neo4j_is_not_contacted_at_all_in_offline_mode(self):
        from tools import graph_memory

        env = {"OFFLINE_MODE": "1", "NEO4J_URI": "neo4j+s://x", "NEO4J_USERNAME": "u", "NEO4J_PASSWORD": "p"}
        with patch.dict("os.environ", env), patch("neo4j.GraphDatabase.driver", side_effect=AssertionError("network used")):
            graph_memory._driver = None
            self.assertIsNone(graph_memory._get_driver())

    @unittest.skipUnless(VOICE_READY, "local voice model files are not installed")
    def test_voice_falls_back_to_the_local_engine_for_every_cloud_choice(self):
        import numpy as np

        fake = MagicMock()
        fake.create.return_value = (np.zeros(2400, dtype="float32"), 24000)
        for engine in ("orpheus", "edge", "auto"):
            with patch.dict("os.environ", {"OFFLINE_MODE": "1"}), patch("api.app.kokoro_engine", return_value=fake):
                r = self.client.post("/voice", json={"text": "hello", "engine": engine})
            self.assertEqual(r.status_code, 200, engine)
            self.assertEqual(r.headers["content-type"], "audio/wav", engine)

    def test_voice_reports_unavailable_when_nothing_can_speak(self):
        with patch.dict("os.environ", {"OFFLINE_MODE": "1"}), patch("api.app.Path.exists", return_value=False):
            r = self.client.post("/voice", json={"text": "hello", "engine": "orpheus"})
        self.assertEqual(r.status_code, 503)


class ServiceWorkerTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_served_from_root_with_scope_and_no_caching(self):
        r = self.client.get("/sw.js")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers["service-worker-allowed"], "/")
        self.assertIn("no-cache", r.headers["cache-control"])
        self.assertIn("javascript", r.headers["content-type"])

    def test_never_caches_posts_or_the_api(self):
        source = self.client.get("/sw.js").text
        self.assertIn("request.method !== 'GET'", source)
        for private in ("/support", "/tutor/stream", "/challenges/check", "/health"):
            self.assertNotIn(f"'{private}'", source)

    def test_data_endpoints_are_matched_exactly_never_ignoring_the_query(self):
        """A ?track=java request must never be answered with the cached ?track=python list."""
        source = self.client.get("/sw.js").text
        self.assertEqual(source.count("ignoreSearch"), 1)
        guarded = source[source.index("ignoreSearch") - 120 : source.index("ignoreSearch") + 30]
        self.assertIn("/static/", guarded)

    def test_pages_register_it_and_practice_can_use_local_python(self):
        html = self.client.get("/static/app.js").text
        self.assertIn("serviceWorker.register('/sw.js')", html)
        practice = self.client.get("/static/practice.js").text
        self.assertIn("/static/vendor/pyodide/", practice)


class OfflineAssetScriptTests(unittest.TestCase):
    LOCK = {"packages": {
        "pandas": {"file_name": "pandas.whl", "sha256": "aa", "depends": ["numpy", "python-dateutil"]},
        "numpy": {"file_name": "numpy.whl", "sha256": "bb", "depends": []},
        "python-dateutil": {"file_name": "dateutil.whl", "sha256": "cc", "depends": ["six"]},
        "six": {"file_name": "six.whl", "sha256": "dd", "depends": []},
    }}

    def test_dependencies_come_first_and_only_once(self):
        order = fetch_assets.resolve_packages(self.LOCK, ["pandas", "numpy"])
        self.assertEqual(sorted(order), ["numpy", "pandas", "python-dateutil", "six"])
        self.assertLess(order.index("numpy"), order.index("pandas"))
        self.assertLess(order.index("six"), order.index("python-dateutil"))

    def test_unknown_package_is_an_error(self):
        with self.assertRaises(KeyError):
            fetch_assets.resolve_packages(self.LOCK, ["not-a-package"])

    def test_plan_lists_core_files_and_verified_wheels(self):
        items = fetch_assets.plan(self.LOCK, ["pandas"])
        files = [i["file"] for i in items]
        for core in ("pyodide.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"):
            self.assertIn(core, files)
        self.assertEqual({i["file"]: i["sha256"] for i in items}["pandas.whl"], "aa")

    def test_a_tampered_download_is_refused_and_not_saved(self):
        import tempfile

        client = MagicMock()
        client.get.return_value = MagicMock(content=b"evil bytes")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(SystemExit):
            fetch_assets.download([{"file": "pandas.whl", "sha256": "0" * 64}], Path(tmp), client)
        self.assertFalse((Path(tmp) / "pandas.whl").exists())

    def test_vendor_folder_is_git_ignored(self):
        self.assertIn("api/static/vendor/", (ROOT / ".gitignore").read_text())


if __name__ == "__main__":
    unittest.main()
