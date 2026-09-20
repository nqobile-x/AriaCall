from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

JEV_MODEL = "typesafe-ai/jev"
AI_GATEWAY_BASE = "https://ai-gateway.vercel.sh/v1"


async def score_response(
    user_message: str,
    aria_response: str,
    escalated: bool = False,
    has_faq_sources: bool = False,
) -> dict:
    """
    Grade an Aria response using Jev evaluation model via Vercel AI Gateway.
    Returns a dict with score (0-100) and breakdown per criterion.
    Runs silently — never blocks the user-facing response.
    """
    api_key = os.getenv("JEV_API_KEY", "").strip()
    if not api_key:
        return _empty_score("JEV_API_KEY not configured")

    state = (
        f"User asked: {user_message}\n"
        f"Aria responded: {aria_response}\n"
        f"Escalated to human: {escalated}\n"
        f"Used knowledge base sources: {has_faq_sources}"
    )

    questions = {
        "answered_question": {
            "type": "boolean",
            "instructions": "Did the agent actually answer or address the user's question?",
        },
        "professional_tone": {
            "type": "boolean",
            "instructions": "Was the response professional, polite and helpful in tone?",
        },
        "correct_escalation": {
            "type": "boolean",
            "instructions": (
                "If the user expressed frustration, urgency or asked for a human — "
                "did the agent escalate or offer to escalate? "
                "If the user did NOT express frustration, answer true."
            ),
        },
        "concise_and_clear": {
            "type": "boolean",
            "instructions": "Was the response concise and easy to understand, without unnecessary filler?",
        },
    }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{AI_GATEWAY_BASE}/evaluate",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": JEV_MODEL, "state": state, "questions": questions},
            )

            if resp.status_code != 200:
                logger.warning("Jev scorer returned %s: %s", resp.status_code, resp.text[:200])
                return _empty_score(f"Jev API error {resp.status_code}")

            data = resp.json()
            breakdown = data.get("questions", {})
            passed = sum(1 for v in breakdown.values() if v.get("value") is True)
            total = len(breakdown)
            score = round((passed / total) * 100) if total else 0

            return {
                "score": score,
                "passed": passed,
                "total": total,
                "needs_review": score < 75,
                "breakdown": {
                    k: v.get("value") for k, v in breakdown.items()
                },
            }

    except Exception as exc:
        logger.warning("Jev scorer exception: %s", exc)
        return _empty_score(str(exc))


def _empty_score(reason: str) -> dict:
    return {
        "score": None,
        "passed": None,
        "total": None,
        "needs_review": False,
        "breakdown": {},
        "error": reason,
    }
