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

    def test_plain_email(self):
        r = self._extract("test@example.com")
        self.assertEqual(r["email"], "test@example.com")
        self.assertIsNone(r["name"])

    def test_name_and_email_labelled(self):
        r = self._extract("name : nqobile   email : nqobile@test.com")
        self.assertEqual(r["name"], "nqobile")
        self.assertEqual(r["email"], "nqobile@test.com")

    def test_natural_sentence(self):
        r = self._extract("My name is Aria and my email is aria@test.com")
        self.assertIsNotNone(r["name"])
        self.assertIn("aria", r["name"].lower())
        self.assertEqual(r["email"], "aria@test.com")

    def test_just_name_no_email(self):
        r = self._extract("just a name no email")
        self.assertIsNone(r["name"])
        self.assertIsNone(r["email"])

    def test_colon_format(self):
        r = self._extract("Nqobile, nqobile@example.com")
        self.assertEqual(r["email"], "nqobile@example.com")


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
