from __future__ import annotations

import asyncio
import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)
from io import BytesIO
from pathlib import Path
from uuid import uuid4

# ── PERFORMANCE: concurrency gate (max 10 simultaneous Groq calls) ────────────
_GROQ_SEMAPHORE = asyncio.Semaphore(10)

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from api.auth import get_company_id, verify_api_key
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.support_agent import SupportAgent

load_dotenv()
app = FastAPI(title="Aria Support Agent", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
agent = SupportAgent()


class SupportRequest(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    customer_id: str | None = None
    conversation_id: str | None = None


class SupportResponse(BaseModel):
    conversation_id: str
    response: str
    customer: dict | None
    account_status: dict | None
    faq_sources: list[dict]
    ticket: dict | None
    escalated: bool
    audit_logged: bool
    learning_suggestion: dict | None


class VoiceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    engine: str = "orpheus"  # "orpheus" | "edge" | "kokoro"


class TranscriptionResponse(BaseModel):
    text: str


class ExportPdfRequest(BaseModel):
    to_email: str
    recipient_name: str = "Learner"
    messages: list[dict]  # [{role: "user"|"aria", text: "..."}]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm": "groq" if os.getenv("GROQ_API_KEY") else "local fallback"}


@app.get("/debug-groq")
def debug_groq() -> dict:
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        return {"error": "GROQ_API_KEY not set", "key_preview": None}
    try:
        import httpx
        from groq import Groq
        completion = Groq(api_key=key, timeout=10.0).chat.completions.create(
            model="openai/gpt-oss-20b",
            messages=[{"role": "user", "content": "Say hi in one word"}],
            max_tokens=10,
        )
        return {"status": "ok", "response": completion.choices[0].message.content, "key_preview": key[:8] + "..."}
    except Exception as exc:
        return {"error": type(exc).__name__, "detail": str(exc), "key_preview": key[:8] + "..."}


@app.get("/", include_in_schema=False)
def landing() -> FileResponse:
    return FileResponse(static_dir / "landing.html")


@app.get("/chat", include_in_schema=False)
def interface() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/admin", include_in_schema=False)
def admin_panel() -> FileResponse:
    return FileResponse(static_dir / "admin.html")


@lru_cache(maxsize=1)
def kokoro_engine():
    from kokoro_onnx import Kokoro
    model_dir = Path("voice/models")
    # phonemizer copies eSpeak's Windows DLL to a temporary path before use.
    # Keep that local to the project so it works in restricted environments.
    temp_dir = Path("voice/.runtime-tmp").resolve()
    temp_dir.mkdir(parents=True, exist_ok=True)
    os.environ["TEMP"] = str(temp_dir)
    os.environ["TMP"] = str(temp_dir)
    return Kokoro(str(model_dir / "kokoro-v1.0.onnx"), str(model_dir / "voices-v1.0.bin"))


@lru_cache(maxsize=1)
def whisper_engine():
    from faster_whisper import WhisperModel
    cache_dir = Path("voice/.whisper-cache").resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache_dir)
    return WhisperModel("base.en", device="cpu", compute_type="int8", download_root=str(cache_dir), local_files_only=True)


@app.post("/voice", responses={200: {"content": {"audio/mpeg": {}, "audio/wav": {}}}})
async def voice(request: VoiceRequest) -> Response:
    engine = request.engine
    groq_key = os.getenv("GROQ_API_KEY")

    # Orpheus — Groq neural TTS via streaming httpx (avoids buffering full WAV in RAM)
    if engine in ("orpheus", "auto") and groq_key:
        try:
            import httpx

            async def orpheus_stream():
                async with httpx.AsyncClient(timeout=30.0) as client:
                    async with client.stream(
                        "POST",
                        "https://api.groq.com/openai/v1/audio/speech",
                        headers={"Authorization": f"Bearer {groq_key}", "Content-Type": "application/json"},
                        json={"model": "canopylabs/orpheus-v1-english", "voice": "diana", "response_format": "wav", "input": request.text},
                    ) as r:
                        if r.status_code != 200:
                            body = await r.aread()
                            logger.error("Orpheus TTS error %s: %s", r.status_code, body[:300])
                            return
                        async for chunk in r.aiter_bytes(chunk_size=8192):
                            yield chunk

            gen = orpheus_stream()
            # Peek: start the generator; if it errors immediately fall through
            first = None
            async for chunk in gen:
                first = chunk
                break
            if first is not None:
                async def _full_stream(first=first, gen=gen):
                    yield first
                    async for c in gen:
                        yield c
                return StreamingResponse(_full_stream(), media_type="audio/wav")
            logger.error("Orpheus TTS returned no audio")
        except Exception as exc:
            logger.error("Orpheus TTS exception: %s", exc)
        if engine != "auto":
            raise HTTPException(status_code=503, detail="Orpheus TTS unavailable.")

    # Edge TTS — Microsoft AriaNeural (free, no key), stream directly
    if engine in ("edge", "auto"):
        try:
            import edge_tts

            async def edge_stream():
                communicate = edge_tts.Communicate(request.text, voice="en-US-AriaNeural", rate="+5%", pitch="+0Hz")
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        yield chunk["data"]

            gen = edge_stream()
            first = None
            async for chunk in gen:
                first = chunk
                break
            if first is not None:
                async def _edge_full(first=first, gen=gen):
                    yield first
                    async for c in gen:
                        yield c
                return StreamingResponse(_edge_full(), media_type="audio/mpeg")
        except Exception as exc:
            logger.error("Edge TTS exception: %s", exc)
            if engine != "auto":
                raise HTTPException(status_code=503, detail="Edge TTS unavailable.")

    # Kokoro ONNX — local neural voice
    if engine in ("kokoro", "auto"):
        model_path = Path("voice/models/kokoro-v1.0.onnx")
        voices_path = Path("voice/models/voices-v1.0.bin")
        if model_path.exists() and model_path.stat().st_size >= 100_000_000 and voices_path.exists():
            try:
                import soundfile as sf
                audio, sample_rate = kokoro_engine().create(request.text, voice="af_heart", speed=1.03, lang="en-us")
                buffer = BytesIO()
                sf.write(buffer, audio, sample_rate, format="WAV")
                return Response(content=buffer.getvalue(), media_type="audio/wav")
            except Exception:
                if engine != "auto":
                    raise HTTPException(status_code=503, detail="Kokoro TTS unavailable.")

    raise HTTPException(status_code=503, detail="No TTS engine available.")


@app.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe(audio: UploadFile = File(...)) -> TranscriptionResponse:
    """Transcribe browser-recorded audio using local Faster-Whisper."""
    if not (audio.content_type or "").startswith("audio/"):
        raise HTTPException(status_code=415, detail="Please upload recorded audio.")
    temp_dir = Path("voice/.runtime-tmp").resolve()
    temp_dir.mkdir(parents=True, exist_ok=True)
    recording = temp_dir / f"recording-{uuid4().hex}.webm"
    try:
        data = await audio.read()
        if len(data) < 1000:
            raise HTTPException(status_code=400, detail="Recording too short — hold the mic button and speak clearly.")
        recording.write_bytes(data)
        # vad_filter=False so Whisper attempts transcription even on quiet recordings
        segments, _ = whisper_engine().transcribe(str(recording), beam_size=5, vad_filter=False, language="en")
        text = " ".join(segment.text.strip() for segment in segments).strip()
        if not text:
            raise HTTPException(status_code=400, detail="No speech detected — try speaking closer to the mic.")
        return TranscriptionResponse(text=text)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Local transcription failed.") from exc
    finally:
        recording.unlink(missing_ok=True)


@app.post("/upload")
async def upload_doc(
    file: UploadFile = File(...),
    company_id: str = Depends(get_company_id),
) -> dict:
    """Ingest a PDF, DOCX or TXT file into Pinecone for RAG search."""
    allowed = {"pdf", "docx", "doc", "txt"}
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=415, detail=f"Unsupported file type .{ext}. Use PDF, DOCX or TXT.")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large — max 10MB.")
    try:
        from tools.rag import parse_file, ingest_document
        text = parse_file(data, file.filename)
        if not text.strip():
            raise HTTPException(status_code=422, detail="Could not extract text from file.")
        chunks = ingest_document(text, company_id=company_id, doc_title=file.filename)
        return {"status": "ok", "file": file.filename, "chunks_indexed": chunks, "company_id": company_id}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {exc}") from exc


@app.get("/admin/tickets")
def admin_tickets(company: dict = Depends(verify_api_key)) -> list[dict]:
    from agents.support_agent import get_tickets
    return get_tickets(company["company_id"])


@app.get("/admin/docs")
def admin_docs(company: dict = Depends(verify_api_key)) -> list[dict]:
    try:
        from tools.rag import _get_client
        pc, index = _get_client()
        if not pc:
            return []
        # Query with zero vector to list all docs for this company
        import os
        dummy = [0.0] * 1024
        results = index.query(
            vector=dummy,
            top_k=100,
            filter={"company_id": {"$eq": company["company_id"]}},
            include_metadata=True,
        )
        seen, docs = set(), []
        for m in results.matches:
            title = m.metadata.get("title", "Unknown")
            if title not in seen:
                seen.add(title)
                docs.append({"title": title, "chunks": 0})
        # Count chunks per doc
        for m in results.matches:
            title = m.metadata.get("title", "Unknown")
            for d in docs:
                if d["title"] == title:
                    d["chunks"] += 1
        return docs
    except Exception as exc:
        logger.error("admin_docs error: %s", exc)
        return []


@app.get("/admin/stats")
def admin_stats(company: dict = Depends(verify_api_key)) -> dict:
    from agents.support_agent import get_tickets
    from tools.graph_memory import top_topics
    tickets = get_tickets(company["company_id"])
    topics_list = top_topics(limit=1)
    docs = admin_docs(company)
    return {
        "company": company["name"],
        "total_tickets": len(tickets),
        "docs_indexed": len(docs),
        "top_topic": topics_list[0]["topic"] if topics_list else "None yet",
    }


@app.get("/topics")
def topics() -> list[dict]:
    """Return the most-asked FAQ topics from Neo4j memory."""
    try:
        from tools.graph_memory import top_topics
        return top_topics(limit=20)
    except Exception:
        return []



@app.post("/data/profile")
async def data_profile(file: UploadFile = File(...)) -> dict:
    """Upload a CSV/Excel/JSON file and get a data quality profile back."""
    allowed = {"csv", "xlsx", "xls", "json"}
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=415, detail=f"Unsupported type .{ext}. Use CSV, XLSX or JSON.")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large — max 10MB.")
    try:
        from tools.data_cleaner import parse_upload, profile_dataframe
        df = parse_upload(data, file.filename)
        profile = profile_dataframe(df)
        return {"status": "ok", "file": file.filename, "profile": profile}
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/data/clean")
async def data_clean(
    file: UploadFile = File(...),
    mode: str = "clean",  # "clean" | "script"
) -> Response:
    """
    Clean a CSV/Excel file and return the cleaned file (mode=clean)
    or a reusable Python script (mode=script).
    """
    allowed = {"csv", "xlsx", "xls", "json"}
    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=415, detail=f"Unsupported type .{ext}.")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large — max 10MB.")
    try:
        from tools.data_cleaner import clean_dataframe, dataframe_to_bytes, generate_cleaning_script, parse_upload, profile_dataframe
        df = parse_upload(data, file.filename)
        profile = profile_dataframe(df)

        if mode == "script":
            script = generate_cleaning_script(file.filename, profile)
            return Response(
                content=script,
                media_type="text/plain",
                headers={"Content-Disposition": f"attachment; filename=clean_{file.filename}.py"},
            )

        cleaned = clean_dataframe(df)
        out_bytes, media_type = dataframe_to_bytes(cleaned, file.filename)
        rows_removed = profile["rows"] - len(cleaned)
        return Response(
            content=out_bytes,
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename=cleaned_{file.filename}",
                "X-Rows-Before": str(profile["rows"]),
                "X-Rows-After": str(len(cleaned)),
                "X-Rows-Removed": str(rows_removed),
                "X-Issues-Found": str(profile["issue_count"]),
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/support/stream")
async def support_stream(request: SupportRequest, company: dict = Depends(verify_api_key)) -> StreamingResponse:
    import json as _json
    from tools.cache import get as cache_get, set as cache_set

    async def generate():
        loop = asyncio.get_event_loop()
        conv_id = request.conversation_id or str(uuid4())

        # Check cache first (only for stateless one-off questions, not mid-conversation)
        cached = None
        if not request.conversation_id:
            cached = cache_get(company["company_id"], request.message)

        if cached:
            logger.info("Cache HIT for company=%s", company["company_id"])
            text = cached.get("response", "")
            words = text.split(" ")
            for i, word in enumerate(words):
                chunk = word + (" " if i < len(words) - 1 else "")
                yield f"data: {_json.dumps({'type': 'token', 'text': chunk})}\n\n"
                await asyncio.sleep(0.025)
            yield f"data: {_json.dumps({'type': 'done', 'conversation_id': conv_id, 'ticket': cached.get('ticket'), 'escalated': cached.get('escalated', False), 'faq_sources': cached.get('faq_sources', []), 'audit_logged': False, 'learning_suggestion': cached.get('learning_suggestion'), 'quality': None, 'cached': True})}\n\n"
            return

        try:
            async with _GROQ_SEMAPHORE:
                result = await loop.run_in_executor(None, lambda: agent.handle(
                    message=request.message,
                    customer_id=request.customer_id,
                    conversation_id=conv_id,
                    company_id=company["company_id"],
                ))
        except Exception as exc:
            yield f"data: {_json.dumps({'type': 'error', 'detail': str(exc)})}\n\n"
            return

        text = result.get("response", "")

        # Cache non-escalated, non-ticket responses for repeat questions
        if not result.get("escalated") and not result.get("ticket") and not request.conversation_id:
            cache_set(company["company_id"], request.message, result)

        words = text.split(" ")
        for i, word in enumerate(words):
            chunk = word + (" " if i < len(words) - 1 else "")
            yield f"data: {_json.dumps({'type': 'token', 'text': chunk})}\n\n"
            await asyncio.sleep(0.035)

        # Silent quality scoring — never blocks the user
        quality = None
        try:
            from tools.jev_scorer import score_response
            quality = await score_response(
                user_message=request.message,
                aria_response=text,
                escalated=result.get("escalated", False),
                has_faq_sources=bool(result.get("faq_sources")),
            )
        except Exception as _qe:
            logger.warning("Jev scoring skipped: %s", _qe)

        yield f"data: {_json.dumps({'type': 'done', 'conversation_id': conv_id, 'ticket': result.get('ticket'), 'escalated': result.get('escalated', False), 'faq_sources': result.get('faq_sources', []), 'audit_logged': result.get('audit_logged', False), 'learning_suggestion': result.get('learning_suggestion'), 'quality': quality, 'cached': False})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/support", response_model=SupportResponse)
def support(request: SupportRequest, company: dict = Depends(verify_api_key)) -> SupportResponse:
    try:
        result = agent.handle(
            message=request.message,
            customer_id=request.customer_id,
            conversation_id=request.conversation_id or str(uuid4()),
            company_id=company["company_id"],
        )
        return SupportResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/support/export-pdf")
async def export_pdf(request: ExportPdfRequest, company: dict = Depends(verify_api_key)):
    """Generate a PDF transcript and email it to the user."""
    import asyncio
    from tools.pdf_generator import generate_conversation_pdf
    from api.email_sender import send_pdf_email

    loop = asyncio.get_event_loop()
    pdf_bytes = await loop.run_in_executor(
        None,
        lambda: generate_conversation_pdf(request.messages, company.get("name", "AriaCall")),
    )
    sent = await loop.run_in_executor(
        None,
        lambda: send_pdf_email(
            to_email=request.to_email,
            recipient_name=request.recipient_name,
            pdf_bytes=pdf_bytes,
            filename="aria-transcript.pdf",
        ),
    )
    if not sent:
        raise HTTPException(status_code=503, detail="Email could not be sent — check Gmail credentials.")
    return {"sent": True, "to": request.to_email}


# ── PHASE 5: CODE EXECUTION (E2B sandbox / safe local fallback) ───────────────
class CodeRunRequest(BaseModel):
    code: str = Field(min_length=1, max_length=10_000)
    language: str = "python"  # only python supported for now


@app.post("/code/run")
async def run_code(request: CodeRunRequest, company: dict = Depends(verify_api_key)):
    if request.language.lower() != "python":
        raise HTTPException(status_code=400, detail="Only Python execution is supported.")
    from tools.e2b_runner import run_python
    result = await asyncio.get_event_loop().run_in_executor(None, lambda: run_python(request.code))
    return result


# ── PHASE 5: CACHE STATS ──────────────────────────────────────────────────────
@app.get("/admin/cache")
def cache_stats(company: dict = Depends(verify_api_key)) -> dict:
    from tools.cache import stats
    return stats()
