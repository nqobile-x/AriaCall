"""Audio Overviews (podcast mode): script parsing, fallbacks, interruptions, voices and download."""

import asyncio
import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import app as app_module
from main import app
from tools import podcast
from tools.resilience import llm_breaker

HEADERS = {"X-API-Key": "aria-demo-key-2024"}
ONLINE = {"GROQ_API_KEY": "test-key", "OFFLINE_MODE": "", "TUTOR_CACHE": "on"}


class ApiError(Exception):
    def __init__(self, status_code):
        super().__init__("boom")
        self.status_code = status_code


def sse_events(response):
    return [json.loads(part[6:]) for part in response.text.split("\n\n") if part.startswith("data: ")]


def reset():
    llm_breaker.record_success()
    podcast.script_cache.clear()
    podcast.audio_cache.clear()


class ParserTests(unittest.TestCase):
    def test_lines_split_across_stream_chunks_are_reassembled(self):
        parser = podcast.ScriptParser()
        out = []
        for chunk in ["ARIA: Welcome to the sh", "ow.\nLEO: Thanks", " for having me.\nARIA: Let's go."]:
            out += parser.feed(chunk)
        self.assertEqual([l["speaker"] for l in out], ["aria"])  # a line is released only once the next one starts
        out += parser.flush()
        self.assertEqual(out, [
            {"speaker": "aria", "text": "Welcome to the show."},
            {"speaker": "leo", "text": "Thanks for having me."},
            {"speaker": "aria", "text": "Let's go."},
        ])

    def test_wrapped_turns_markdown_and_stage_directions_are_cleaned(self):
        lines = podcast.parse_script("# Episode title\n**ARIA:** So *this* is [music] important.\nIt carries on here.\n- leo : (laughs) Right! 🎉\n")
        self.assertEqual(lines, [
            {"speaker": "aria", "text": "So this is important. It carries on here."},
            {"speaker": "leo", "text": "Right!"},
        ])

    def test_very_long_turns_are_split_at_sentences(self):
        text = "ARIA: " + " ".join(f"Sentence number {i} is here." for i in range(40))
        lines = podcast.parse_script(text)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(len(l["text"]) <= podcast.MAX_LINE_CHARS and l["speaker"] == "aria" for l in lines))

    def test_text_outside_any_turn_is_ignored(self):
        self.assertEqual(podcast.parse_script("Here is your script:\n\nnothing else"), [])


class OfflineEpisodeTests(unittest.TestCase):
    def test_offline_episode_is_read_from_the_knowledge_base(self):
        sources = [{"title": "Resetting your password", "text": "Select Forgot password on the sign-in page. The reset link expires after 30 minutes."}]
        lines = podcast.offline_script("password resets", sources)
        joined = " ".join(l["text"] for l in lines)
        self.assertIn("Resetting your password", joined)
        self.assertIn("30 minutes", joined)
        self.assertEqual({l["speaker"] for l in lines}, {"aria", "leo"})

    def test_offline_episode_without_sources_does_not_guess(self):
        joined = " ".join(l["text"] for l in podcast.offline_script("quantum billing", []))
        self.assertIn("don't want to guess", joined)

    def test_offline_answer_repeats_the_question_and_returns_to_the_episode(self):
        lines = podcast.offline_answer("How long is the link valid?", [{"title": "Resetting your password", "text": "The reset link expires after 30 minutes."}])
        self.assertIn("How long is the link valid?", lines[0]["text"])
        self.assertIn("30 minutes", lines[1]["text"])
        self.assertEqual(lines[-1]["speaker"], "leo")


class ScriptEventTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_without_a_key_a_built_in_episode_is_served(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "OFFLINE_MODE": ""}):
            events = list(podcast.script_events("reset my password", length="short"))
        self.assertEqual(events[0]["type"], "sources")
        self.assertIn("Resetting your password", events[0]["items"])
        self.assertTrue(any(e["type"] == "notice" for e in events))
        self.assertGreater(sum(e["type"] == "line" for e in events), 3)

    def test_model_lines_stream_out_and_are_cached(self):
        script = "ARIA: Hi there.\nLEO: Hello!\nARIA: Today, passwords.\nLEO: Great.\nARIA: Bye."
        with patch.dict(os.environ, ONLINE), patch.object(podcast, "_stream_model", return_value=iter(script)) as model:
            first = [e for e in podcast.script_events("passwords", length="short") if e["type"] == "line"]
            second = [e for e in podcast.script_events("passwords", length="short") if e["type"] == "line"]
        self.assertEqual(len(first), 5)
        self.assertEqual(first, second)
        self.assertEqual(model.call_count, 1, "a repeated episode is served from the cache")

    def test_notes_are_sent_to_the_model_as_a_source(self):
        with patch.dict(os.environ, ONLINE), patch.object(podcast, "_stream_model", return_value=iter("ARIA: a.\nLEO: b.\nARIA: c.\nLEO: d.")) as model:
            list(podcast.script_events("our Q3 plan", notes="Launch in Durban in October."))
        prompt = model.call_args[0][0][1]["content"]
        self.assertIn("Your notes", prompt)
        self.assertIn("Launch in Durban in October.", prompt)

    def test_a_line_cut_off_mid_sentence_is_dropped(self):
        def broken(*_):
            yield "ARIA: One.\nLEO: Two.\nARIA: And the second thing is"
            raise ApiError(503)
        with patch.dict(os.environ, ONLINE), patch.object(podcast, "_stream_model", side_effect=broken):
            texts = [e["text"] for e in podcast.script_events("topic y") if e["type"] == "line"]
        self.assertEqual(texts[:2], ["One.", "Two."])
        self.assertNotIn("And the second thing is", texts)

    def test_a_dropped_connection_ends_the_episode_honestly(self):
        def broken(*_):
            yield "ARIA: One.\nLEO: Two.\n"
            raise ApiError(503)
        with patch.dict(os.environ, ONLINE), patch.object(podcast, "_stream_model", side_effect=broken):
            events = list(podcast.script_events("topic x"))
        lines = [e for e in events if e["type"] == "line"]
        self.assertEqual([l["text"] for l in lines[:2]], ["One.", "Two."])
        self.assertIn("leave it there", lines[-1]["text"])
        self.assertTrue(any(e["type"] == "notice" and "part-way" in e["text"] for e in events))

    def test_a_rejected_key_trips_the_breaker_and_falls_back(self):
        with patch.dict(os.environ, ONLINE), patch.object(podcast, "_stream_model", side_effect=ApiError(401)) as model:
            events = list(podcast.script_events("reset my password"))
        self.assertEqual(model.call_count, 1, "a bad key is not retried on other models")
        self.assertEqual(llm_breaker.state()["status"], "down")
        self.assertGreater(sum(e["type"] == "line" for e in events), 3)

    def test_transient_errors_retry_then_try_the_next_model(self):
        calls = []

        def flaky(messages, model, max_tokens):
            calls.append(model)
            if len(calls) < 3:
                raise ApiError(429)
            return iter("ARIA: a.\nLEO: b.\nARIA: c.\nLEO: d.")
        with patch.dict(os.environ, ONLINE), patch.object(podcast, "_stream_model", side_effect=flaky), patch("tools.tutor.model_chain", return_value=["m1", "m2"]):
            lines = [e for e in podcast.script_events("anything") if e["type"] == "line"]
        self.assertEqual(calls, ["m1", "m1", "m2"])
        self.assertEqual(len(lines), 4)


class AnswerTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_answer_uses_the_model_and_the_recent_dialogue(self):
        reply = "LEO: A listener asks how long the link lasts.\nARIA: Thirty minutes.\nLEO: Back to it."
        recent = [{"speaker": "aria", "text": "Click Forgot password."}]
        with patch.dict(os.environ, ONLINE), patch.object(podcast, "_complete_model", return_value=reply) as model:
            result = podcast.answer_lines("passwords", "How long does the link last?", recent)
        self.assertIsNone(result["notice"])
        self.assertEqual([l["speaker"] for l in result["lines"]], ["leo", "aria", "leo"])
        prompt = model.call_args[0][0][1]["content"]
        self.assertIn("Click Forgot password.", prompt)
        self.assertIn("How long does the link last?", prompt)

    def test_answer_falls_back_to_the_knowledge_base(self):
        with patch.dict(os.environ, ONLINE), patch.object(podcast, "_complete_model", side_effect=ApiError(500)):
            result = podcast.answer_lines("passwords", "How do I reset my password?", [])
        self.assertTrue(result["notice"])
        self.assertIn("forgot password", " ".join(l["text"] for l in result["lines"]).lower())


class VoiceAndDownloadTests(unittest.TestCase):
    def setUp(self):
        reset()

    def test_each_host_has_a_distinct_voice_and_lines_are_cached(self):
        voices = []

        async def fake_edge(text, voice):
            voices.append(voice)
            return b"\xff\xf3" + text.encode()
        with patch.dict(os.environ, {"OFFLINE_MODE": ""}), patch.object(podcast, "_edge_audio", side_effect=fake_edge):
            asyncio.run(podcast.synthesize("Hi", "aria", "za"))
            asyncio.run(podcast.synthesize("Hi", "leo", "za"))
            asyncio.run(podcast.synthesize("Hi", "leo", "za"))
        self.assertEqual(voices, ["en-ZA-LeahNeural", "en-ZA-LukeNeural"])

    def test_download_joins_the_lines_into_one_mp3_reusing_played_audio(self):
        calls = []

        async def fake_edge(text, voice):
            calls.append(text)
            return b"<" + text.encode() + b">"
        lines = [{"speaker": "aria", "text": "One."}, {"speaker": "leo", "text": "Two."}]
        with patch.dict(os.environ, {"OFFLINE_MODE": ""}), patch.object(podcast, "_edge_audio", side_effect=fake_edge):
            asyncio.run(podcast.synthesize("One.", "aria"))  # already played in the browser
            audio, media_type = asyncio.run(podcast.build_episode(lines))
        self.assertEqual((audio, media_type), (b"<One.><Two.>", "audio/mpeg"))
        self.assertEqual(calls, ["One.", "Two."])


class EndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def setUp(self):
        reset()
        for pair in (app_module._podcast_limiter, app_module._podcast_ask_limiter, app_module._podcast_voice_limiter, app_module._podcast_download_limiter):
            for limiter in pair:
                limiter._hits.clear()

    def test_script_endpoint_streams_sources_lines_and_done(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "OFFLINE_MODE": ""}):
            response = self.client.post("/podcast/script", headers=HEADERS, json={"topic": "reset my password", "length": "short"})
        self.assertEqual(response.status_code, 200)
        events = sse_events(response)
        self.assertEqual(events[0]["type"], "sources")
        self.assertEqual(events[-1]["type"], "done")
        self.assertTrue(all(e["speaker"] in ("aria", "leo") for e in events if e["type"] == "line"))

    def test_script_endpoint_needs_a_key_and_validates_input(self):
        self.assertEqual(self.client.post("/podcast/script", json={"topic": "x y"}).status_code, 401)
        self.assertEqual(self.client.post("/podcast/script", headers=HEADERS, json={"topic": "x"}).status_code, 422)
        self.assertEqual(self.client.post("/podcast/script", headers=HEADERS, json={"topic": "ok topic", "length": "forever"}).status_code, 422)

    def test_new_episodes_are_rate_limited_per_browser(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "OFFLINE_MODE": ""}):
            codes = [self.client.post("/podcast/script", headers={**HEADERS, "X-Client-Id": "pod-limit"}, json={"topic": "billing"}).status_code for _ in range(7)]
        self.assertEqual(codes[:6], [200] * 6)
        self.assertEqual(codes[6], 429)

    def test_ask_endpoint_returns_lines(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "", "OFFLINE_MODE": ""}):
            response = self.client.post("/podcast/ask", headers=HEADERS, json={
                "topic": "passwords", "question": "How do I reset my password?",
                "recent": [{"speaker": "leo", "text": "So what's first?"}],
            })
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.json()["lines"]), 2)

    def test_ask_rejects_unknown_speakers(self):
        response = self.client.post("/podcast/ask", headers=HEADERS, json={"topic": "t t", "question": "q q", "recent": [{"speaker": "narrator", "text": "hi"}]})
        self.assertEqual(response.status_code, 422)

    def test_voice_endpoint_returns_audio_or_503(self):
        async def ok(*_args, **_kwargs):
            return b"ID3fake", "audio/mpeg"

        async def fail(*_args, **_kwargs):
            raise RuntimeError("no voice")
        with patch.object(podcast, "synthesize", side_effect=ok):
            response = self.client.post("/podcast/voice", headers=HEADERS, json={"text": "Hello", "speaker": "leo"})
        self.assertEqual((response.status_code, response.headers["content-type"], response.content), (200, "audio/mpeg", b"ID3fake"))
        with patch.object(podcast, "synthesize", side_effect=fail):
            self.assertEqual(self.client.post("/podcast/voice", headers=HEADERS, json={"text": "Hello"}).status_code, 503)

    def test_download_endpoint_names_the_file_after_the_topic(self):
        async def fake_build(lines, accent):
            return b"".join(l["text"].encode() for l in lines), "audio/mpeg"
        with patch.object(podcast, "build_episode", side_effect=fake_build):
            response = self.client.post("/podcast/download", headers=HEADERS, json={"title": "How Billing Works!", "lines": [{"speaker": "aria", "text": "A"}, {"speaker": "leo", "text": "B"}]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"AB")
        self.assertIn('filename="how-billing-works.mp3"', response.headers["content-disposition"])

    def test_extract_reads_text_files_and_rejects_others(self):
        ok = self.client.post("/podcast/extract", headers=HEADERS, files={"file": ("notes.md", b"# Plan\n\nShip it in October.", "text/markdown")})
        self.assertEqual(ok.status_code, 200)
        self.assertIn("Ship it in October.", ok.json()["text"])
        bad = self.client.post("/podcast/extract", headers=HEADERS, files={"file": ("run.exe", b"MZ", "application/octet-stream")})
        self.assertEqual(bad.status_code, 415)


if __name__ == "__main__":
    unittest.main()
