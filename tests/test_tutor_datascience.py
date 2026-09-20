"""Tests for the data-science track: lessons, statistical-pitfall checks, analyse mode."""

import ast
import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app
from tools import tutor
from tools.tutor_datascience import lint_ds_rules
from tools.e2b_runner import run_python


# Tests must not depend on whether a local Ollama happens to be running on this machine.
os.environ["LOCAL_LLM"] = "off"
os.environ["TUTOR_CACHE"] = "off"  # cache behaviour has its own tests
os.environ["TUTOR_RATE_LIMIT"] = "100000"

HEADERS = {"X-API-Key": "aria-demo-key-2024"}


def _messages(code):
    return " ".join(f["message"] for f in tutor.lint_code(code, "datascience"))


class DataScienceLintTests(unittest.TestCase):
    def test_leakage_detected_only_when_fit_precedes_split(self):
        bad = "scaler = StandardScaler()\nX = scaler.fit_transform(X)\nX_tr, X_te = train_test_split(X, random_state=1)\n"
        good = "X_tr, X_te = train_test_split(X, random_state=1)\nscaler = StandardScaler()\nX_tr = scaler.fit_transform(X_tr)\nX_te = scaler.transform(X_te)\n"
        self.assertIn("leakage", _messages(bad))
        self.assertNotIn("leakage", _messages(good))

    def test_missing_random_state(self):
        self.assertIn("random_state", _messages("a = train_test_split(X, y)\n"))
        self.assertNotIn("random_state", _messages("a = train_test_split(X, y, random_state=42)\n"))

    def test_pandas_pitfalls(self):
        code = "df['a'].fillna(0, inplace=True)\ndf[df.x > 1]['y'] = 3\nfor i, r in df.iterrows():\n    pass\ndf = df.append(other)\n"
        msgs = _messages(code)
        for expected in ("inplace=True", "Chained assignment", "iterrows", "removed in pandas 2.0"):
            self.assertIn(expected, msgs)

    def test_loc_assignment_is_clean(self):
        self.assertEqual(lint_ds_rules("df.loc[df.x > 1, 'y'] = 3\n"), [])

    def test_truncated_bar_axis(self):
        self.assertIn("y-axis", _messages("plt.bar(a, b)\nplt.ylim(97, 101)\n"))
        self.assertNotIn("y-axis", _messages("plt.bar(a, b)\nplt.ylim(0, 101)\n"))
        self.assertNotIn("y-axis", _messages("plt.plot(a, b)\nplt.ylim(97, 101)\n"))

    def test_accuracy_only_evaluation(self):
        self.assertIn("Accuracy alone", _messages("accuracy_score(a, b)\n"))
        self.assertNotIn("Accuracy alone", _messages("accuracy_score(a, b)\nf1_score(a, b)\n"))

    def test_syntax_error_reported_once_and_ds_rules_skipped(self):
        found = tutor.lint_code("df.fillna(0, inplace=True\n", "datascience")
        self.assertEqual([f["severity"] for f in found], ["error"])

    def test_findings_are_not_duplicated(self):
        msgs = [f["message"] for f in tutor.lint_code("a.fillna(0, inplace=True)\na.fillna(0, inplace=True)\n", "datascience")]
        self.assertEqual(len(msgs), len(set(msgs)))


class DataScienceLessonTests(unittest.TestCase):
    def test_path_is_complete_and_starters_parse(self):
        lessons = tutor.lessons_for("datascience")
        self.assertGreaterEqual(len(lessons), 10)
        for lesson in lessons:
            ast.parse(lesson["starter"])

    def test_teaching_points_are_demonstrated_by_the_starters(self):
        found = {l["id"]: tutor.lint_code(l["starter"], "datascience") for l in tutor.lessons_for("datascience")}
        self.assertTrue(any("leakage" in f["message"] for f in found["ds-8"]))
        self.assertTrue(any("y-axis" in f["message"] for f in found["ds-5"]))
        self.assertTrue(any("Chained" in f["message"] for f in found["ds-3"]))
        self.assertTrue(any("Accuracy" in f["message"] for f in found["ds-9"]))


class DataSciencePromptTests(unittest.TestCase):
    def test_persona_forbids_invented_numbers(self):
        system = tutor.build_messages(language="datascience", level="beginner", mode="explain", code="x = 1")[0]["content"]
        self.assertIn("senior data scientist", system)
        self.assertIn("Never invent numbers", system)

    def test_other_tracks_do_not_get_the_data_persona(self):
        system = tutor.build_messages(language="java", level="beginner", mode="explain", code="class A {}")[0]["content"]
        self.assertNotIn("data scientist", system)

    def test_analyse_needs_context_and_marks_it_untrusted(self):
        with self.assertRaises(ValueError):
            tutor.build_messages(language="datascience", level="beginner", mode="analyse")
        msgs = tutor.build_messages(language="datascience", level="beginner", mode="analyse", context="Rows: 3")
        self.assertIn("untrusted", msgs[1]["content"])
        self.assertIn("never the rows", msgs[1]["content"])
        self.assertIn("untrusted", msgs[0]["content"])

    def test_context_is_capped(self):
        msgs = tutor.build_messages(language="datascience", level="beginner", mode="analyse", context="x" * 9000)
        self.assertLess(msgs[1]["content"].count("x"), tutor.MAX_CONTEXT_CHARS + 10)


class DataScienceEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        from tools.resilience import CircuitBreaker
        for patcher in (patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}), patch("tools.resilience.llm_breaker", CircuitBreaker())):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _post(self, body):
        return self.client.post("/tutor/stream", json=body, headers=HEADERS)

    def test_analyse_validation(self):
        self.assertEqual(self._post({"language": "datascience", "mode": "analyse"}).status_code, 400)
        self.assertEqual(self._post({"language": "java", "mode": "analyse", "context": "Rows: 1"}).status_code, 400)
        self.assertEqual(self._post({"language": "datascience", "mode": "analyse", "context": "x" * 4001}).status_code, 422)

    def test_analyse_streams(self):
        with patch("tools.tutor.stream_tutor", return_value=iter(["plan"])):
            r = self._post({"language": "datascience", "mode": "analyse", "context": "Rows: 3\nColumns: 2"})
        events = [json.loads(x[6:]) for x in r.text.split("\n\n") if x.startswith("data: ")]
        self.assertEqual([e["type"] for e in events], ["token", "done"])

    def test_lessons_endpoint_and_review_lint(self):
        r = self.client.get("/tutor/lessons", params={"language": "datascience"}, headers=HEADERS)
        self.assertEqual(len(r.json()), 10)
        with patch("tools.tutor.stream_tutor", return_value=iter(["ok"])):
            r = self._post({"language": "datascience", "mode": "review", "code": "df['a'].fillna(0, inplace=True)\n"})
        self.assertEqual(json.loads(r.text.split("\n\n")[0][6:])["type"], "lint")

    def test_code_run_accepts_datascience_and_explains_missing_sandbox(self):
        with patch.dict("os.environ", {"E2B_API_KEY": ""}):
            r = self.client.post("/code/run", json={"code": "import pandas as pd\n", "language": "datascience"}, headers=HEADERS)
        self.assertEqual(r.status_code, 200)
        self.assertIn("E2B", r.json()["error"])


class RunnerTests(unittest.TestCase):
    def test_plain_python_still_runs_locally(self):
        with patch.dict("os.environ", {"E2B_API_KEY": ""}):
            self.assertEqual(run_python("print(2 + 3)")["stdout"].strip(), "5")

    def test_imports_get_a_clear_message_not_a_cryptic_error(self):
        with patch.dict("os.environ", {"E2B_API_KEY": ""}):
            result = run_python("import numpy as np\nprint(1)")
        self.assertIn("E2B_API_KEY", result["error"])


if __name__ == "__main__":
    unittest.main()
