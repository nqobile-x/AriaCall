from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

CUSTOMERS = {
    "demo-001": {"id": "demo-001", "name": "Amina Patel", "email": "amina@example.com", "plan": "Pro"},
    "demo-002": {"id": "demo-002", "name": "Sam Mokoena", "email": "sam@example.com", "plan": "Starter"},
}
FAQS = [
    {"title": "About Aria", "text": "I am Aria, a customer-support agent. I can look up customers, check account status, search the support knowledge base, explain billing and account policies, create escalation tickets for urgent issues, and log our interaction. Ask me what you need help with."},
    {"title": "Resetting your password", "text": "Select Forgot password on the sign-in page. The reset link expires after 30 minutes."},
    {"title": "Updating billing details", "text": "Open Settings, then Billing, to update your payment method and download invoices."},
    {"title": "Cancelling a subscription", "text": "Subscriptions can be cancelled from Settings > Billing and remain active until the end of the current period."},
]


def customer_lookup(customer_id: str | None, message: str) -> dict | None:
    if customer_id:
        return CUSTOMERS.get(customer_id)
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", message)
    if email_match:
        email = email_match.group(0).lower()
        return next((c for c in CUSTOMERS.values() if c["email"] == email), None)
    return None


def account_status_checker(customer: dict | None) -> dict | None:
    if not customer:
        return None
    return {"customer_id": customer["id"], "status": "active", "plan": customer["plan"], "billing_current": True}


def faq_search(message: str) -> list[dict]:
    """Retrieve from the Obsidian knowledge base, falling back to starter FAQs.

    Scoring: title word-hits are worth 3x body hits, normalised by document
    length so a long catch-all document cannot win on volume alone.
    """
    tokens = set(re.findall(r"[a-z]{3,}", message.lower()))
    if not tokens:
        return []
    documents = _knowledge_base_documents() + FAQS

    def score(item: dict) -> float:
        title_tokens = set(re.findall(r"[a-z]{3,}", item["title"].lower()))
        body_tokens = re.findall(r"[a-z]{3,}", item["text"].lower())
        body_unique = set(body_tokens)
        title_hits = len(tokens & title_tokens)
        body_hits = len(tokens & body_unique)
        # Normalise body hits by vocab size to penalise very long catch-all docs.
        body_score = body_hits / max(len(body_unique), 1) * 10
        return title_hits * 3 + body_score

    ranked = sorted(documents, key=score, reverse=True)
    return [item for item in ranked[:3] if score(item) > 0]


def _knowledge_base_documents() -> list[dict]:
    """Load and chunk Obsidian notes using LangChain, with no hosted vector DB."""
    vault = Path(os.getenv("OBSIDIAN_VAULT", "obsidian-vault"))
    kb_dir = vault / "Aria Support" / "Knowledge Base"
    if not kb_dir.exists():
        return []
    try:
        from langchain_community.document_loaders import DirectoryLoader, TextLoader
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        raw_documents = DirectoryLoader(
            str(kb_dir), glob="**/*.md", loader_cls=TextLoader, loader_kwargs={"encoding": "utf-8"}
        ).load()
        chunks = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100).split_documents(raw_documents)
        documents = []
        for chunk in chunks:
            source = Path(chunk.metadata["source"])
            text = chunk.page_content.strip()
            heading = re.search(r"^#\s+(.+)$", text, flags=re.MULTILINE)
            title = heading.group(1).strip() if heading else source.stem.replace("-", " ")
            body = re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL)
            body = re.sub(r"^#\s+.+$", "", body, flags=re.MULTILINE).strip()
            if body:
                documents.append({"title": title, "text": body, "path": str(source)})
        return documents
    except (ImportError, OSError):
        # The starter FAQs still keep the service available if the local loader fails.
        return []


def escalation_trigger(message: str, account_status: dict | None) -> dict:
    urgent_terms = (
        "fraud", "charged twice", "chargeback", "legal", "lawsuit",
        "security breach", "human agent", "refund", "data breach",
        "account hacked", "unauthorized", "not working for weeks",
        "escalate", "speak to manager", "this is unacceptable",
    )
    msg_lower = message.lower()
    match = next((term for term in urgent_terms if term in msg_lower), None)
    if match:
        return {"required": True, "reason": f"Escalation phrase detected: '{match}'"}
    # Detect frustrated/angry tone via exclamation clusters or strong negative language
    if msg_lower.count("!") >= 3 or any(w in msg_lower for w in ("furious", "disgusted", "terrible service", "worst")):
        return {"required": True, "reason": "High frustration detected in message tone"}
    if account_status and not account_status["billing_current"]:
        return {"required": True, "reason": "Account has an unresolved billing issue"}
    return {"required": False, "reason": None}


def create_ticket(state: dict, reason: str | None) -> dict:
    return {"id": f"ARIA-{uuid4().hex[:8].upper()}", "status": "open", "reason": reason, "created_at": datetime.now(UTC).isoformat()}


def propose_knowledge_note(state: dict) -> dict | None:
    """Create a review-only learning note; it never changes active knowledge."""
    try:
        vault = Path(os.getenv("OBSIDIAN_VAULT", "obsidian-vault"))
        queue = vault / "Aria Support" / "Knowledge Base" / "Review Queue"
        queue.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC)
        note_id = uuid4().hex[:6]
        note = queue / f"review_{now:%Y-%m-%d}_{note_id}.md"
        note.write_text(
            f"---\nstatus: needs-review\ncreated: {now.isoformat()}\nsource: aria-learning-queue\n---\n\n"
            f"# Proposed knowledge: {state['message'][:70]}\n\n## Customer question\n\n{state['message']}\n\n"
            "## Proposed answer\n\n_Add an accurate, approved answer here before moving this note out of Review Queue._\n",
            encoding="utf-8",
        )
        return {"status": "needs-review", "path": str(note)}
    except OSError:
        return None


def draft_response(state: dict, use_groq: bool = False) -> str:
    name = (state.get("customer") or {}).get("name", "there")
    account = state.get("account_status")
    faq_sources = state.get("faq_sources") or []

    if state.get("escalated"):
        ticket_id = (state.get("ticket") or {}).get("id", "N/A")
        return (
            f"Hi {name}, I completely understand — this needs immediate attention. "
            f"I've opened ticket **{ticket_id}** and flagged it as urgent. "
            f"A member of our team will reach out to you shortly."
        )

    if use_groq:
        try:
            from groq import Groq

            # Build rich context from all matched FAQs
            if faq_sources:
                context_parts = [f"[{i+1}] {s['title']}: {s['text']}" for i, s in enumerate(faq_sources)]
                context = "\n".join(context_parts)
            else:
                context = "No specific FAQ matched. Use your general knowledge to help, but do not invent account-specific data."

            account_info = ""
            if account:
                account_info = f"\nCustomer plan: {account['plan']} | Status: {account['status']}"

            system_prompt = (
                "You are Aria, a warm, sharp, and efficient customer support agent. "
                "You speak naturally — like a knowledgeable person, not a script. "
                "Keep replies concise (2-4 sentences). "
                "Ground every factual claim in the knowledge-base context below. "
                "Never invent policies, prices, or account-specific data. "
                "If you genuinely don't know, say a specialist will follow up — don't guess."
            )

            history = state.get("history") or []
            messages = [
                {"role": "system", "content": system_prompt},
                *history,
                {
                    "role": "user",
                    "content": (
                        f"Customer name: {name}{account_info}\n"
                        f"Their message: {state['message']}\n\n"
                        f"Knowledge base context:\n{context}"
                    ),
                },
            ]
            completion = Groq().chat.completions.create(
                model="llama-3.3-70b-versatile",
                temperature=0.3,
                max_tokens=220,
                messages=messages,
            )
            content = completion.choices[0].message.content
            if content:
                return content.strip()
        except Exception:
            pass

    # Fallback: use best FAQ directly
    if faq_sources:
        source = faq_sources[0]
        return f"Hi {name}, {source['text']}\n\n_Source: {source['title']}_"
    return (
        f"Hi {name}, thanks for getting in touch! "
        "I wasn't able to find an exact match for that in our knowledge base, "
        "but I've logged your message and our team will follow up with you soon."
    )


def _redact_pii(text: str) -> str:
    """Strip PII from text before writing to the audit log."""
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine

        analyzer = AnalyzerEngine()
        anonymizer = AnonymizerEngine()
        results = analyzer.analyze(text=text, language="en")
        return anonymizer.anonymize(text=text, analyzer_results=results).text
    except Exception:
        # Fall back to a simple email/phone scrub if presidio is unavailable.
        cleaned = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", text)
        cleaned = re.sub(r"\b\d[\d\s\-().]{6,}\d\b", "[PHONE]", cleaned)
        return cleaned


def log_interaction(state: dict) -> bool:
    try:
        vault = Path(os.getenv("OBSIDIAN_VAULT", "obsidian-vault"))
        log_dir = vault / "Aria Support" / "Interactions"
        log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC)
        note = log_dir / f"{now:%Y-%m-%d_%H%M%S}_{state['conversation_id'][:8]}_{uuid4().hex[:6]}.md"
        ticket = state.get("ticket") or {}
        safe_message = _redact_pii(state["message"])
        safe_response = _redact_pii(state["response"])
        note.write_text(
            f"---\ncreated: {now.isoformat()}\nconversation_id: {state['conversation_id']}\n"
            f"customer_id: {state.get('customer_id') or 'unknown'}\nescalated: {str(state['escalated']).lower()}\n"
            f"ticket_id: {ticket.get('id', '')}\n---\n\n# Customer interaction\n\n"
            f"## Message\n\n{safe_message}\n\n## Aria response\n\n{safe_response}\n"
            f"\n## FAQ sources\n\n" + "\n".join(f"- {item['title']}" for item in state.get("faq_sources", [])),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False
