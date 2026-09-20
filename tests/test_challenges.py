"""Quality gate for the practice/interview bank and its grading, with no API key involved."""

import importlib.util
import json
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from main import app
from tools import challenges
from tools.challenge_bank import CHALLENGES, POINTS
from tools.challenges import RateLimiter, grade_mcq, grade_rubric

HEADERS = {"X-API-Key": "aria-demo-key-2024"}
HARNESS_PATH = Path(__file__).parent.parent / "api" / "static" / "challenge_harness.py"

_spec = importlib.util.spec_from_file_location("challenge_harness", HARNESS_PATH)
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

CODE = [c for c in CHALLENGES if c["type"] == "code"]
RUBRIC = [c for c in CHALLENGES if c["type"] == "rubric"]
MCQ = [c for c in CHALLENGES if c["type"] == "mcq"]


class BankIntegrityTests(unittest.TestCase):
    def test_every_track_is_covered_at_every_difficulty(self):
        for track in challenges.TRACKS:
            items = challenges.list_public(track)
            self.assertGreaterEqual(len(items), 7, track)
            self.assertTrue({"easy", "medium", "hard"} <= {i["difficulty"] for i in items}, track)

    def test_ids_unique_and_required_fields(self):
        ids = [c["id"] for c in CHALLENGES]
        self.assertEqual(len(ids), len(set(ids)))
        for c in CHALLENGES:
            for key in ("track", "type", "difficulty", "title", "prompt", "explanation", "hints"):
                self.assertTrue(c.get(key), f"{c['id']} missing {key}")
            self.assertIn(c["difficulty"], POINTS)

    def test_mcq_answers_are_valid_and_options_distinct(self):
        for c in MCQ:
            self.assertEqual(len(set(c["options"])), len(c["options"]), c["id"])
            self.assertIn(c["answer"], range(len(c["options"])), c["id"])

    def test_public_view_never_leaks_answers(self):
        for track in challenges.TRACKS:
            items = challenges.list_public(track)
            blob = json.dumps(items)
            for item in items:
                for secret in ("solution", "rubric", "answer", "explanation"):
                    self.assertNotIn(secret, item, f"{item['id']} leaks '{secret}'")
            for c in CHALLENGES:
                if c["track"] != track or not c.get("solution"):
                    continue
                public_text = " ".join([c["starter"], c["prompt"], *c["hints"]])
                secret_lines = [ln.strip() for ln in c["solution"].splitlines() if len(ln.strip()) > 25 and ln.strip() not in public_text and ln.strip().split("(")[0] not in public_text]
                for line in secret_lines:
                    self.assertNotIn(json.dumps(line)[1:-1], blob, f"{c['id']} leaks solution line: {line}")


class PythonAndDataScienceGradingTests(unittest.TestCase):
    """Real execution through the same harness the browser uses."""

    def test_every_reference_solution_passes_all_tests(self):
        for c in CODE:
            result = harness.run_challenge(c["solution"], c["tests"])
            failures = [r for r in result["results"] if not r["passed"]]
            self.assertTrue(result["ok"], f"{c['id']}: {result['error']}")
            self.assertTrue(result["passed"], f"{c['id']} solution fails: {failures}")
            self.assertGreaterEqual(len(result["results"]), 2, c["id"])

    def test_every_starter_fails(self):
        for c in CODE:
            result = harness.run_challenge(c["starter"], c["tests"])
            self.assertFalse(result["passed"], f"{c['id']}: the starter code must not pass")

    def test_wrong_and_broken_submissions_are_reported_not_raised(self):
        tests = next(c["tests"] for c in CODE if c["id"] == "py-1")
        wrong = harness.run_challenge("def is_palindrome(text):\n    return text == text[::-1]\n", tests)
        self.assertTrue(wrong["ok"])
        self.assertFalse(wrong["passed"])
        self.assertTrue(any(not r["passed"] and r["message"] for r in wrong["results"]))
        self.assertFalse(harness.run_challenge("def is_palindrome(:", tests)["ok"])
        crash = harness.run_challenge("def is_palindrome(text):\n    raise ValueError('boom')\n", tests)
        self.assertTrue(all("ValueError" in r["message"] for r in crash["results"]))
        exits = harness.run_challenge("import sys\nsys.exit(1)\n", tests)
        self.assertFalse(exits["ok"])

    def test_missing_function_gives_a_clear_message(self):
        tests = next(c["tests"] for c in CODE if c["id"] == "py-1")
        result = harness.run_challenge("x = 1\n", tests)
        self.assertFalse(result["passed"])
        self.assertIn("KeyError", result["results"][0]["message"])

    def test_learner_output_is_captured_and_capped(self):
        tests = next(c["tests"] for c in CODE if c["id"] == "py-1")
        result = harness.run_challenge("print('x' * 5000)\ndef is_palindrome(t):\n    return True\n", tests)
        self.assertLessEqual(len(result["stdout"]), 2000)

    def test_a_partial_solution_gets_partial_credit(self):
        tests = next(c["tests"] for c in CODE if c["id"] == "py-1")
        result = harness.run_challenge("def is_palindrome(text):\n    return text == text[::-1]\n", tests)
        passed = sum(r["passed"] for r in result["results"])
        self.assertTrue(0 < passed < len(result["results"]))


class StaticGradingTests(unittest.TestCase):
    def test_every_reference_solution_passes_its_rubric(self):
        for c in RUBRIC:
            result = grade_rubric(c, c["solution"])
            bad = [k["description"] for k in result["checks"] if not k["ok"]]
            self.assertTrue(result["passed"], f"{c['id']} solution fails checks: {bad}")

    def test_every_starter_fails_at_least_one_check(self):
        for c in RUBRIC:
            self.assertFalse(grade_rubric(c, c["starter"])["passed"], f"{c['id']} starter must not pass")

    def test_comments_and_strings_cannot_fake_a_pass(self):
        c = next(c for c in RUBRIC if c["id"] == "sp-9")
        cheat = "// @Bean SecurityFilterChain authorizeHttpRequests requestMatchers anyRequest().authenticated() SessionCreationPolicy.STATELESS\n" \
                'String s = "authorizeHttpRequests requestMatchers( anyRequest().authenticated()";\n'
        self.assertFalse(grade_rubric(c, cheat)["passed"])

    def test_forbidden_patterns_are_penalised(self):
        c = next(c for c in RUBRIC if c["id"] == "sp-9")
        bad = c["solution"].replace(".anyRequest().authenticated()", ".anyRequest().permitAll()")
        result = grade_rubric(c, bad)
        self.assertFalse(result["passed"])
        self.assertTrue(any(k["id"] == "open-all" and not k["ok"] for k in result["checks"]))

    def test_feedback_says_what_to_fix(self):
        c = next(c for c in RUBRIC if c["id"] == "jv-4")
        result = grade_rubric(c, c["starter"])
        failing = [k for k in result["checks"] if not k["ok"]]
        self.assertTrue(failing)
        self.assertTrue(all(k["message"] for k in failing))
        self.assertIsNone(result["explanation"])

    def test_mcq_grading(self):
        c = MCQ[0]
        self.assertTrue(grade_mcq(c, c["answer"])["passed"])
        wrong = (c["answer"] + 1) % len(c["options"])
        result = grade_mcq(c, wrong)
        self.assertFalse(result["passed"])
        self.assertEqual(result["points"], 0)
        self.assertTrue(result["explanation"])

    def test_no_java_is_executed(self):
        import inspect
        source = inspect.getsource(challenges)
        for banned in ("subprocess", "os.system", "exec(", "eval("):
            self.assertNotIn(banned, source)


class RateLimiterTests(unittest.TestCase):
    def test_limits_per_key_and_recovers(self):
        now = [0.0]
        limiter = RateLimiter(limit=3, window=10, clock=lambda: now[0])
        self.assertTrue(all(limiter.allow("a") for _ in range(3)))
        self.assertFalse(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))
        now[0] = 11
        self.assertTrue(limiter.allow("a"))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        challenges.limiter._hits.clear()

    def test_requires_api_key_and_valid_track(self):
        self.assertEqual(self.client.get("/challenges", params={"track": "python"}).status_code, 401)
        self.assertEqual(self.client.get("/challenges", params={"track": "cobol"}, headers=HEADERS).status_code, 422)

    def test_list_serves_tests_for_browser_grading_but_no_secrets(self):
        items = self.client.get("/challenges", params={"track": "python"}, headers=HEADERS).json()
        code = next(i for i in items if i["type"] == "code")
        self.assertIn("tests", code)
        self.assertEqual(code["graded"], "browser")
        self.assertNotIn("solution", code)
        mcq = next(i for i in items if i["type"] == "mcq")
        self.assertNotIn("answer", mcq)
        self.assertGreaterEqual(len(mcq["options"]), 2)

    def test_check_mcq_and_rubric(self):
        r = self.client.post("/challenges/check", json={"id": "sp-1", "choice": 0}, headers=HEADERS)
        self.assertTrue(r.json()["passed"])
        r = self.client.post("/challenges/check", json={"id": "sp-1", "choice": 2}, headers=HEADERS)
        self.assertFalse(r.json()["passed"])
        ref = next(c for c in RUBRIC if c["id"] == "sp-6")
        r = self.client.post("/challenges/check", json={"id": "sp-6", "code": ref["solution"]}, headers=HEADERS)
        self.assertTrue(r.json()["passed"])
        self.assertTrue(r.json()["static"])

    def test_check_validation(self):
        post = lambda body: self.client.post("/challenges/check", json=body, headers=HEADERS)
        self.assertEqual(post({"id": "nope", "choice": 0}).status_code, 404)
        self.assertEqual(post({"id": "py-1", "code": "x"}).status_code, 400)  # graded in the browser
        self.assertEqual(post({"id": "sp-1"}).status_code, 400)
        self.assertEqual(post({"id": "sp-1", "choice": 7}).status_code, 400)
        self.assertEqual(post({"id": "sp-6", "code": "  "}).status_code, 400)
        self.assertEqual(post({"id": "sp-6", "code": "x" * 10_001}).status_code, 422)

    def test_solution_endpoint(self):
        r = self.client.post("/challenges/solution", json={"id": "py-1"}, headers=HEADERS).json()
        self.assertIn("def is_palindrome", r["solution"])
        self.assertTrue(r["explanation"])
        self.assertEqual(self.client.post("/challenges/solution", json={"id": "zzz"}, headers=HEADERS).status_code, 404)

    def test_rate_limit_protects_the_server(self):
        challenges.limiter.limit = 5
        try:
            codes = [self.client.post("/challenges/check", json={"id": "sp-1", "choice": 0}, headers=HEADERS).status_code for _ in range(7)]
        finally:
            challenges.limiter.limit = 90
        self.assertEqual(codes[:5], [200] * 5)
        self.assertEqual(codes[5:], [429, 429])

    def test_works_with_no_llm_key(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {"GROQ_API_KEY": ""}):
            self.assertEqual(self.client.get("/challenges", params={"track": "java"}, headers=HEADERS).status_code, 200)
            self.assertEqual(self.client.post("/challenges/check", json={"id": "jv-1", "choice": 1}, headers=HEADERS).status_code, 200)

    def test_harness_is_served_as_a_static_file(self):
        r = self.client.get("/static/challenge_harness.py")
        self.assertEqual(r.status_code, 200)
        self.assertIn("def run_challenge", r.text)


if __name__ == "__main__":
    unittest.main()
