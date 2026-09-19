from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

EMBED_MODEL = "multilingual-e5-large"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50


def _get_client():
    api_key = (os.getenv("PINECONE_API_KEY") or "").strip()
    if not api_key:
        return None, None
    try:
        from pinecone import Pinecone
        pc = Pinecone(api_key=api_key)
        index = pc.Index(os.getenv("PINECONE_INDEX", "aria-kb"))
        return pc, index
    except Exception as exc:
        logger.warning("Pinecone unavailable: %s", exc)
        return None, None


def _chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    chunks, current = [], ""
    for sentence in sentences:
        if len(current) + len(sentence) > CHUNK_SIZE:
            if current:
                chunks.append(current.strip())
            current = sentence
        else:
            current = (current + " " + sentence).strip()
    if current:
        chunks.append(current.strip())
    return [c for c in chunks if len(c) > 30]


def _embed(pc, texts: list[str], input_type: str = "passage") -> list[list[float]]:
    result = pc.inference.embed(
        model=EMBED_MODEL,
        inputs=texts,
        parameters={"input_type": input_type, "truncate": "END"},
    )
    return [r.values for r in result]


def ingest_document(text: str, company_id: str, doc_title: str) -> int:
    """Chunk, embed and upsert a document. Returns number of chunks stored."""
    pc, index = _get_client()
    if not pc:
        return 0
    chunks = _chunk_text(text)
    if not chunks:
        return 0
    try:
        embeddings = _embed(pc, chunks, input_type="passage")
        vectors = [
            {
                "id": f"{company_id}_{doc_title}_{i}",
                "values": emb,
                "metadata": {
                    "text": chunk,
                    "company_id": company_id,
                    "title": doc_title,
                },
            }
            for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
        ]
        index.upsert(vectors=vectors)
        logger.info("Ingested %d chunks for %s / %s", len(vectors), company_id, doc_title)
        return len(vectors)
    except Exception as exc:
        logger.error("Pinecone ingest error: %s", exc)
        return 0


def rag_search(query: str, company_id: str = "default", top_k: int = 5) -> list[dict[str, Any]]:
    """Semantic search — returns top matching chunks."""
    pc, index = _get_client()
    if not pc:
        return []
    try:
        q_emb = _embed(pc, [query], input_type="query")[0]
        results = index.query(
            vector=q_emb,
            top_k=top_k,
            filter={"company_id": {"$eq": company_id}},
            include_metadata=True,
        )
        return [
            {
                "title": m.metadata.get("title", "Document"),
                "text": m.metadata.get("text", ""),
                "score": round(m.score, 3),
            }
            for m in results.matches
            if m.score > 0.4
        ]
    except Exception as exc:
        logger.error("Pinecone search error: %s", exc)
        return []


def parse_file(file_bytes: bytes, filename: str) -> str:
    """Extract text from PDF, DOCX or plain text."""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext == "pdf":
        try:
            import PyPDF2, io
            reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
            return "\n".join(p.extract_text() or "" for p in reader.pages)
        except Exception as exc:
            logger.error("PDF parse error: %s", exc)
            return ""
    if ext in ("docx", "doc"):
        try:
            import docx, io
            doc = docx.Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as exc:
            logger.error("DOCX parse error: %s", exc)
            return ""
    return file_bytes.decode("utf-8", errors="ignore")
