"""Quick smoke tests for CORS middleware and contact extraction."""

import sys
import os
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("GROQ_API_KEY", "fake")
os.environ.setdefault("NEO4J_URI", "bolt://localhost:7687")
os.environ.setdefault("NEO4J_USERNAME", "neo4j")
os.environ.setdefault("NEO4J_PASSWORD", "fake")
os.environ.setdefault("NEO4J_DATABASE", "neo4j")
os.environ.setdefault("PINECONE_API_KEY", "fake")
os.environ.setdefault("PINECONE_INDEX", "aria-kb")
os.environ.setdefault("GMAIL_USER", "fake@gmail.com")
os.environ.setdefault("GMAIL_APP_PASSWORD", "fake")


def _load_extract_contact():
    """Load _extract_contact without importing the full support_agent (avoids langgraph dep)."""
    import importlib.util, pathlib, re
    src = pathlib.Path(__file__).parent.parent / "agents" / "support_agent.py"
    code = src.read_text(encoding="utf-8")
    # Execute only up to the first external import that would fail
    safe = "\n".join(
        line for line in code.splitlines()
        if not any(x in line for x in ["from langgraph", "from neo4j", "from pinecone", "from groq"])
    )
    ns = {"__name__": "agents.support_agent", "re": re, "os": os}
    exec(compile(safe, str(src), "exec"), ns)
    return ns["_extract_contact"]


class TestExtractContact(unittest.TestCase):
    def _extract(self, msg):
        return _load_extract_contact()(msg)

    def _name(self, msg):
        return (self._extract(msg)["name"] or "").lower()

    def _email(self, msg):
        return self._extract(msg)["email"]

    # ── email-only ──────────────────────────────────────────────────────────────
    def test_plain_email(self):
        r = self._extract("test@example.com")
        self.assertEqual(r["email"], "test@example.com")
        self.assertIsNone(r["name"])

    def test_just_name_no_email(self):
        r = self._extract("just a name no email")
        self.assertIsNone(r["name"])
        self.assertIsNone(r["email"])

    # ── labeled formats ─────────────────────────────────────────────────────────
    def test_name_label_colon(self):
        self.assertIn("nqobile", self._name("name : nqobile   email : nqobile@test.com"))
        self.assertEqual(self._email("name : nqobile   email : nqobile@test.com"), "nqobile@test.com")

    def test_name_label_is(self):
        self.assertIn("aria", self._name("My name is Aria and my email is aria@test.com"))

    def test_name_after_email_label(self):
        self.assertIn("fatima", self._name("email: fatima@example.com, name: Fatima"))

    # ── natural sentence ────────────────────────────────────────────────────────
    def test_im_prefix(self):
        self.assertIn("nqobza", self._name("I'm Nqobza, nqobza@test.com"))

    def test_iam_prefix(self):
        self.assertIn("sipho", self._name("I am Sipho, sipho@test.com"))

    def test_this_is(self):
        self.assertIn("lerato", self._name("This is Lerato lerato@test.com"))

    def test_call_me(self):
        self.assertIn("sam", self._name("Call me Sam, sam@example.com"))

    def test_here_suffix(self):
        self.assertIn("amina", self._name("Amina here, amina@example.com — charged twice"))

    # ── name before email (comma / dash / space) ────────────────────────────────
    def test_name_comma_email(self):
        self.assertIn("nqobile", self._name("Nqobile, nqobile@example.com"))

    def test_name_dash_email(self):
        self.assertIn("nqobza", self._name("Nqobza - nqobza@example.com charged twice"))

    def test_full_name_before_email(self):
        self.assertIn("amina", self._name("Amina Patel amina@example.com"))

    # ── email before name ───────────────────────────────────────────────────────
    def test_email_then_name(self):
        self.assertIn("nqobza", self._name("nqobza@test.com - Nqobza here"))

    def test_email_comma_name(self):
        self.assertIn("sipho", self._name("sipho@test.com, Sipho Dlamini"))

    # ── sentence with context noise ─────────────────────────────────────────────
    def test_full_sentence_with_issue(self):
        self.assertIn("nqobza", self._name(
            "NQOBZA_08@outlook.com - I was charged twice this month, my name is Nqobza"
        ))

    def test_greeting_then_name(self):
        self.assertIn("lerato", self._name("Hi Lerato, lerato@example.com needs help"))

    # ── colon format (existing) ──────────────────────────────────────────────────
    def test_colon_format(self):
        self.assertEqual(self._email("Nqobile, nqobile@example.com"), "nqobile@example.com")


class TestCORSMiddleware(unittest.TestCase):
    def setUp(self):
        try:
            from fastapi.testclient import TestClient
            from api.app import app
            self.client = TestClient(app)
            self.available = True
        except Exception:
            self.available = False

    def test_cors_header_present(self):
        if not self.available:
            self.skipTest("TestClient deps unavailable")
        resp = self.client.options(
            "/health",
            headers={"Origin": "https://example.com", "Access-Control-Request-Method": "GET"},
        )
        self.assertIn(resp.status_code, [200, 405])
        origin = resp.headers.get("access-control-allow-origin", "")
        self.assertEqual(origin, "*")

    def test_health_cors_header(self):
        if not self.available:
            self.skipTest("TestClient deps unavailable")
        resp = self.client.get("/health", headers={"Origin": "https://myapp.com"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("access-control-allow-origin"), "*")


if __name__ == "__main__":
    unittest.main(verbosity=2)
