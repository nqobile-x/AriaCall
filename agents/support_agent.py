from __future__ import annotations

import os
from typing import Any, TypedDict

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


class SupportState(TypedDict, total=False):
    message: str
    customer_id: str | None
    conversation_id: str
    customer: dict | None
    account_status: dict | None
    faq_sources: list[dict]
    ticket: dict | None
    escalated: bool
    response: str
    audit_logged: bool
    learning_suggestion: dict | None


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
        return {"faq_sources": faq_search(state["message"])}

    def escalate_if_needed(self, state: SupportState) -> dict:
        escalation = escalation_trigger(state["message"], state.get("account_status"))
        ticket = create_ticket(state, escalation["reason"]) if escalation["required"] else None
        return {"escalated": escalation["required"], "ticket": ticket}

    def draft(self, state: SupportState) -> dict:
        return {"response": draft_response(state, use_groq=bool(os.getenv("GROQ_API_KEY")))}

    def propose_learning(self, state: SupportState) -> dict:
        if state.get("faq_sources") or state.get("escalated"):
            return {"learning_suggestion": None}
        return {"learning_suggestion": propose_knowledge_note(state)}

    def log(self, state: SupportState) -> dict:
        return {"audit_logged": log_interaction(state)}

    def handle(self, message: str, customer_id: str | None, conversation_id: str) -> dict[str, Any]:
        if not message.strip():
            raise ValueError("message cannot be empty")
        return dict(self.graph.invoke({"message": message.strip(), "customer_id": customer_id, "conversation_id": conversation_id}))
