from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_driver = None


def _get_driver():
    global _driver
    if _driver is not None:
        return _driver
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USERNAME")
    password = os.getenv("NEO4J_PASSWORD")
    if not (uri and user and password):
        return None
    try:
        from neo4j import GraphDatabase
        _driver = GraphDatabase.driver(uri, auth=(user, password))
        _driver.verify_connectivity()
        logger.info("Neo4j connected: %s", uri)
    except Exception as exc:
        logger.warning("Neo4j unavailable: %s", exc)
        _driver = None
    return _driver


def log_conversation(conversation_id: str, topics: list[str], escalated: bool = False, ticket_id: str | None = None) -> bool:
    """Write a Conversation node linked to Topic nodes. Fire-and-forget — never raises."""
    driver = _get_driver()
    if not driver or not topics:
        return False
    try:
        with driver.session() as session:
            session.execute_write(_write_conversation, conversation_id, topics, escalated, ticket_id)
        return True
    except Exception as exc:
        logger.warning("Neo4j write failed: %s", exc)
        return False


def _write_conversation(tx, conversation_id: str, topics: list[str], escalated: bool, ticket_id: str | None):
    # Merge conversation node
    tx.run(
        "MERGE (c:Conversation {id: $cid}) "
        "SET c.escalated = $escalated, c.updated = timestamp()",
        cid=conversation_id, escalated=escalated,
    )
    # Merge each topic and link
    for topic in topics:
        tx.run(
            "MERGE (t:Topic {name: $name}) "
            "ON CREATE SET t.count = 1 "
            "ON MATCH SET t.count = t.count + 1 "
            "WITH t "
            "MATCH (c:Conversation {id: $cid}) "
            "MERGE (c)-[:ASKED_ABOUT]->(t)",
            name=topic, cid=conversation_id,
        )
    if ticket_id:
        tx.run(
            "MERGE (tk:Ticket {id: $tid}) "
            "WITH tk "
            "MATCH (c:Conversation {id: $cid}) "
            "MERGE (c)-[:CREATED_TICKET]->(tk)",
            tid=ticket_id, cid=conversation_id,
        )


def top_topics(limit: int = 10) -> list[dict[str, Any]]:
    """Return the most-asked topics. Returns [] if Neo4j is unavailable."""
    driver = _get_driver()
    if not driver:
        return []
    try:
        with driver.session() as session:
            result = session.run(
                "MATCH (t:Topic) RETURN t.name AS topic, t.count AS count "
                "ORDER BY t.count DESC LIMIT $limit",
                limit=limit,
            )
            return [{"topic": r["topic"], "count": r["count"]} for r in result]
    except Exception as exc:
        logger.warning("Neo4j read failed: %s", exc)
        return []
