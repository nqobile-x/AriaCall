"""End-to-end checks for the HTTP API, LangGraph workflow, KB, and Obsidian log."""

import unittest

from fastapi.testclient import TestClient

from main import app


class SupportSystemTests(unittest.TestCase):
    HEADERS = {"X-API-Key": "aria-demo-key-2024"}

    def setUp(self) -> None:
        self.client = TestClient(app)

    def tearDown(self) -> None:
        pass

    def test_health(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_grounded_reply_uses_kb_and_logs(self) -> None:
        response = self.client.post("/support", json={"customer_id": "demo-001", "message": "How do I reset my password?"}, headers=self.HEADERS)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(len(body["faq_sources"]) > 0)
        self.assertEqual(body["faq_sources"][0]["title"], "Password Reset")
        self.assertTrue(body["audit_logged"])

    def test_email_lookup_and_escalation_ticket(self) -> None:
        response = self.client.post("/support", json={"message": "amina@example.com says I was charged twice"}, headers=self.HEADERS)
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["customer"]["id"], "demo-001")
        self.assertTrue(body["escalated"])
        self.assertRegex(body["ticket"]["id"], r"^ARIA-[A-F0-9]{8}$")
        self.assertTrue(body["audit_logged"])

    def test_invalid_request_is_rejected(self) -> None:
        response = self.client.post("/support", json={"message": ""}, headers=self.HEADERS)
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
