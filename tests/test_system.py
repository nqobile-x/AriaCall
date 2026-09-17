"""End-to-end checks for the HTTP API, LangGraph workflow, KB, and Obsidian log."""

import os
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from main import app


class SupportSystemTests(unittest.TestCase):
    def setUp(self) -> None:
        self.vault = Path("tests") / ".test-vaults" / uuid4().hex
        self.old_vault = os.environ.get("OBSIDIAN_VAULT")
        os.environ["OBSIDIAN_VAULT"] = str(self.vault)
        kb = self.vault / "Aria Support" / "Knowledge Base"
        kb.mkdir(parents=True)
        (kb / "returns.md").write_text(
            "# Returns policy\n\nCustomers may request a return within 30 days of delivery.", encoding="utf-8"
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        if self.old_vault is None:
            os.environ.pop("OBSIDIAN_VAULT", None)
        else:
            os.environ["OBSIDIAN_VAULT"] = self.old_vault
        shutil.rmtree(self.vault, ignore_errors=True)

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_grounded_reply_uses_obsidian_note_and_logs(self) -> None:
        response = self.client.post("/support", json={"customer_id": "demo-001", "message": "What is your returns policy?"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("30 days", body["response"])
        self.assertEqual(body["faq_sources"][0]["title"], "Returns policy")
        self.assertTrue(body["audit_logged"])
        notes = list((self.vault / "Aria Support" / "Interactions").glob("*.md"))
        self.assertEqual(len(notes), 1)
        self.assertIn("What is your returns policy?", notes[0].read_text(encoding="utf-8"))

    def test_email_lookup_and_escalation_ticket(self) -> None:
        response = self.client.post("/support", json={"message": "amina@example.com says I was charged twice"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["customer"]["id"], "demo-001")
        self.assertTrue(body["escalated"])
        self.assertRegex(body["ticket"]["id"], r"^ARIA-[A-F0-9]{8}$")
        self.assertTrue(body["audit_logged"])

    def test_invalid_request_is_rejected(self) -> None:
        response = self.client.post("/support", json={"message": ""})
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
