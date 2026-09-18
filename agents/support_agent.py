from __future__ import annotations

import os
import re
from collections import defaultdict
from typing import Any, TypedDict


def _extract_contact(message: str) -> dict:
    """Pull name and email from a user message in any format."""
    email_match = re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", message)
    email = email_match.group(0).lower() if email_match else None
    if email and email_match:
        before = message[: email_match.start()]
        # Strip trailing labels: "email address :", "email :", "e-mail:", "my email is", ", email"
        before = re.sub(r"[\s,;]*\b(my\s+)?(e-?mail(\s+address)?|address)(\s+is)?\b[\s:]*$", "", before, flags=re.IGNORECASE)
        # Strip leading labels: "name :", "name:", "my name is"
        before = re.sub(r"^[\s]*\b(my\s+)?name\s*[:\-is]*\s*", "", before, flags=re.IGNORECASE)
        before = before.strip().strip(",.;:")
        name = before if 2 < len(before) < 60 else None
    else:
        name = None
    return {"name": name, "email": email}

from langgraph.graph import END, START, StateGraph

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


class SupportState(TypedDict, total=False):
    message: str
    customer_id: str | None
    conversation_id: str
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
        # Try RAG (Pinecone semantic search) first
        try:
            from tools.rag import rag_search
            rag_results = rag_search(state["message"], company_id="default")
            if rag_results:
                return {"faq_sources": rag_results}
        except Exception:
            pass
        # Fall back to keyword KB
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
            # Don't create ticket yet — ask for contact details first
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

    def handle(self, message: str, customer_id: str | None, conversation_id: str) -> dict[str, Any]:
        if not message.strip():
            raise ValueError("message cannot be empty")
        history = _history[conversation_id][-MAX_HISTORY_TURNS * 2:]
        result = dict(self.graph.invoke({
            "message": message.strip(),
            "customer_id": customer_id,
            "conversation_id": conversation_id,
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
            # Send confirmation email
            customer = result.get("customer") or {}
            ticket = result.get("ticket") or {}
            email = customer.get("email")
            if email:
                from api.email_sender import send_ticket_email
                send_ticket_email(
                    to_email=email,
                    customer_name=customer.get("name", "there"),
                    ticket_id=ticket.get("id", "N/A"),
                    issue=message.strip()[:200],
                )

        _history[conversation_id].append({"role": "user", "content": message.strip()})
        _history[conversation_id].append({"role": "assistant", "content": result.get("response", "")})
        return result
