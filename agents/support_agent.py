from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any, TypedDict


def _extract_contact(message: str) -> dict:
    """Pull name and email from a user message in many natural formats."""
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", message)
    email = email_match.group(0).lower() if email_match else None

    if not email:
        return {"name": None, "email": None}

    # Remove the email + surrounding punctuation/labels to get the rest
    rest = message[: email_match.start()] + " " + message[email_match.end():]
    rest = re.sub(r"\b(e-?mail(\s+address)?|address)\b", " ", rest, flags=re.IGNORECASE)
    rest = rest.strip()

    name = _extract_name_from_text(rest)
    return {"name": name, "email": email}


_STOP_WORD_RE = r"(?:and|or|but|my|is|am|in|at|on|for|with|the|was|that|this|it|a|an|re|fw)"
_NAME_WORD = r"[A-Za-z][A-Za-z\-\']*"
# 1-3 words where each successive word must not be a stop word
_NAME_PAT = rf"({_NAME_WORD}(?:\s+(?!{_STOP_WORD_RE}\b){_NAME_WORD}){{0,2}})"
_END = r"(?=\s*[,;.:\-]|\s+\w{{2,}}|\s*$)"


def _extract_name_from_text(text: str) -> str | None:
    """Try multiple patterns to pull a person's name from free text."""
    # "my name is X" / "name: X" / "name is X"
    m = re.search(rf"\b(?:my\s+)?name\s*(?:is|:|-|=)?\s*{_NAME_PAT}", text, re.IGNORECASE)
    if m and _valid_name(m.group(1).strip()):
        return m.group(1).strip()

    # "I'm X" / "I am X" / "it's X" / "this is X" / "call me X"
    m = re.search(rf"\b(?:i[''`]?m|i\s+am|it[''`]?s|this\s+is|call\s+me)\s+{_NAME_PAT}", text, re.IGNORECASE)
    if m and _valid_name(m.group(1).strip()):
        return m.group(1).strip()

    # "Hi/Hey/Hello, X"
    m = re.search(rf"^\s*(?:hi|hey|hello|good\s+\w+)[,!\s]+{_NAME_PAT}", text, re.IGNORECASE)
    if m and _valid_name(m.group(1).strip()):
        return m.group(1).strip()

    # "X here"
    m = re.search(rf"({_NAME_WORD}(?:\s+{_NAME_WORD}){{0,2}})\s+here\b", text, re.IGNORECASE)
    if m and _valid_name(m.group(1).strip()):
        return m.group(1).strip()

    # Fallback: strip noise, look for title-case sequences
    stripped = re.sub(
        r"\b(my|i|was|is|am|the|a|an|and|or|to|for|of|in|it|its|this|that|me|help|please|hi|hey|hello|thanks|thank|you|dear|sir|madam|re|fw|name|email)\b",
        " ", text, flags=re.IGNORECASE,
    )
    stripped = re.sub(r"[^A-Za-z\s\-\']", " ", stripped)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    m = re.search(r"\b([A-Z][a-z\-\']{1,20}(?:\s+[A-Z][a-z\-\']{1,20}){0,2})\b", stripped)
    if m and _valid_name(m.group(1).strip()):
        return m.group(1).strip()

    return None


def _valid_name(candidate: str) -> bool:
    """Reject single-letter words, stop-word-only strings, and suspicious lengths."""
    stop = {"hi", "hey", "hello", "my", "me", "i", "am", "is", "it", "the", "and", "or",
            "to", "for", "a", "an", "please", "thanks", "thank", "you", "dear", "sir",
            "madam", "help", "good", "morning", "afternoon", "evening", "name", "email",
            "customer", "there"}
    words = candidate.strip().split()
    if not words or len(words) > 4:
        return False
    if all(w.lower() in stop for w in words):
        return False
    if any(len(w) < 2 for w in words):
        return False
    return 2 < len(candidate) < 60

from langgraph.graph import END, START, StateGraph

def get_tickets(company_id: str) -> list[dict]:
    return list(reversed(_tickets[company_id]))


from tools.support_tools import (
    account_status_checker,
    create_ticket,
    customer_lookup,
    draft_response,
    escalation_trigger,
    faq_search,
    log_interaction,
    propose_knowledge_note,
)

# In-memory conversation history: {conversation_id: [{"role": ..., "content": ...}]}
_history: dict[str, list[dict]] = defaultdict(list)
MAX_HISTORY_TURNS = 6

# In-memory ticket store: {company_id: [ticket_dict]}
_tickets: dict[str, list[dict]] = defaultdict(list)


class SupportState(TypedDict, total=False):
    message: str
    customer_id: str | None
    conversation_id: str
    company_id: str
    history: list[dict]
    customer: dict | None
    account_status: dict | None
    faq_sources: list[dict]
    ticket: dict | None
    escalated: bool
    response: str
    audit_logged: bool
    learning_suggestion: dict | None
    _needs_contact: bool
    _awaiting_contact: bool
    _escalation_reason: str | None


class SupportAgent:
    """A small, auditable LangGraph workflow for incoming text messages."""

    def __init__(self) -> None:
        graph = StateGraph(SupportState)
        graph.add_node("lookup_customer", self.lookup_customer)
        graph.add_node("check_account", self.check_account)
        graph.add_node("search_faq", self.search_faq)
        graph.add_node("escalate_if_needed", self.escalate_if_needed)
        graph.add_node("draft", self.draft)
        graph.add_node("propose_learning", self.propose_learning)
        graph.add_node("log", self.log)
        graph.add_edge(START, "lookup_customer")
        graph.add_edge("lookup_customer", "check_account")
        graph.add_edge("check_account", "search_faq")
        graph.add_edge("search_faq", "escalate_if_needed")
        graph.add_edge("escalate_if_needed", "draft")
        graph.add_edge("draft", "propose_learning")
        graph.add_edge("propose_learning", "log")
        graph.add_edge("log", END)
        self.graph = graph.compile()

    def lookup_customer(self, state: SupportState) -> dict:
        return {"customer": customer_lookup(state.get("customer_id"), state["message"])}

    def check_account(self, state: SupportState) -> dict:
        customer = state.get("customer")
        return {"account_status": account_status_checker(customer)}

    def search_faq(self, state: SupportState) -> dict:
        company_id = state.get("company_id", "default")
        try:
            from tools.rag import rag_search
            rag_results = rag_search(state["message"], company_id=company_id)
            if rag_results:
                return {"faq_sources": rag_results}
        except Exception:
            pass
        return {"faq_sources": faq_search(state["message"])}

    def escalate_if_needed(self, state: SupportState) -> dict:
        history = state.get("history") or []
        # Check if we're collecting contact info for a pending escalation
        pending = next((h for h in reversed(history) if h.get("role") == "pending_escalation"), None)
        if pending:
            contact = _extract_contact(state["message"])
            if contact["email"]:
                ticket = create_ticket(state, pending.get("reason", "User requested escalation"))
                return {
                    "escalated": True,
                    "ticket": ticket,
                    "customer": {
                        "name": contact["name"] or "Customer",
                        "email": contact["email"],
                    },
                }
            # Still waiting for valid email
            return {"escalated": False, "ticket": None, "_awaiting_contact": True}

        escalation = escalation_trigger(state["message"], state.get("account_status"))
        if escalation["required"]:
            # If message already has contact info, create ticket immediately
            contact = _extract_contact(state["message"])
            if contact["email"]:
                customer = state.get("customer") or {"name": contact["name"] or "Customer", "email": contact["email"]}
                ticket = create_ticket(state, escalation["reason"])
                return {"escalated": True, "ticket": ticket, "customer": customer}
            # No email in message — ask for contact details first
            return {"escalated": False, "ticket": None, "_needs_contact": True, "_escalation_reason": escalation["reason"]}
        return {"escalated": False, "ticket": None}

    def draft(self, state: SupportState) -> dict:
        if state.get("_needs_contact"):
            return {"response": (
                "I'd be happy to escalate this to our human support team right away. "
                "Could you please share your name and email address so I can create your ticket "
                "and send you a confirmation?"
            )}
        if state.get("_awaiting_contact"):
            return {"response": (
                "I didn't quite catch a valid email address. "
                "Could you share it again? For example: yourname@example.com"
            )}
        return {"response": draft_response(state, use_groq=bool(os.getenv("GROQ_API_KEY")))}

    def propose_learning(self, state: SupportState) -> dict:
        if state.get("faq_sources") or state.get("escalated"):
            return {"learning_suggestion": None}
        return {"learning_suggestion": propose_knowledge_note(state)}

    def log(self, state: SupportState) -> dict:
        logged = log_interaction(state)
        # Extract topic categories from FAQ matches and write to Neo4j
        faq_sources = state.get("faq_sources") or []
        topics = list({s.get("category", s.get("title", "general")) for s in faq_sources if s})
        if topics or state.get("escalated"):
            try:
                from tools.graph_memory import log_conversation
                ticket = state.get("ticket") or {}
                log_conversation(
                    conversation_id=state.get("conversation_id", "unknown"),
                    topics=topics or ["escalation"],
                    escalated=bool(state.get("escalated")),
                    ticket_id=ticket.get("id"),
                )
            except Exception:
                pass
        return {"audit_logged": logged}

    def handle(self, message: str, customer_id: str | None, conversation_id: str, company_id: str = "default") -> dict[str, Any]:
        if not message.strip():
            raise ValueError("message cannot be empty")
        history = _history[conversation_id][-MAX_HISTORY_TURNS * 2:]
        result = dict(self.graph.invoke({
            "message": message.strip(),
            "customer_id": customer_id,
            "conversation_id": conversation_id,
            "company_id": company_id,
            "history": history,
        }))

        # Persist pending escalation so next turn knows to collect contact info
        if result.get("_needs_contact"):
            _history[conversation_id].append({
                "role": "pending_escalation",
                "reason": result.get("_escalation_reason", "User requested escalation"),
            })
        # Clear pending escalation once ticket is created
        elif result.get("escalated"):
            _history[conversation_id] = [
                h for h in _history[conversation_id] if h.get("role") != "pending_escalation"
            ]
            # Store ticket for admin panel
            customer = result.get("customer") or {}
            ticket = result.get("ticket") or {}
            if ticket:
                from datetime import datetime, timezone
                _tickets[company_id].append({
                    **ticket,
                    "customer_name": customer.get("name", "Customer"),
                    "customer_email": customer.get("email", ""),
                    "issue": message.strip()[:200],
                    "created_at": ticket.get("created_at", datetime.now(timezone.utc).isoformat()),
                })
            # Send confirmation email and append status to the response
            email = customer.get("email")
            if email:
                from api.email_sender import send_ticket_email
                sent = send_ticket_email(
                    to_email=email,
                    customer_name=customer.get("name", "there"),
                    ticket_id=ticket.get("id", "N/A"),
                    issue=message.strip()[:200],
                )
                if sent:
                    result["response"] = result.get("response", "") + f" A confirmation has been sent to **{email}**."
                else:
                    result["response"] = result.get("response", "") + " (We couldn't send a confirmation email right now — our team still has your ticket.)"

        _history[conversation_id].append({"role": "user", "content": message.strip()})
        _history[conversation_id].append({"role": "assistant", "content": result.get("response", "")})
        return result
