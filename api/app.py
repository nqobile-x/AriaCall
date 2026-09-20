from __future__ import annotations

import asyncio
import logging
import json as _json_lib
import os
import re
import threading
from functools import lru_cache
from typing import Literal

logger = logging.getLogger(__name__)
from io import BytesIO
from pathlib import Path
from uuid import uuid4

# ── PERFORMANCE: concurrency gate (max 10 simultaneous Groq calls) ────────────
_GROQ_SEMAPHORE = asyncio.Semaphore(10)

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from api.auth import get_company_id, verify_api_key
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
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
    from tools.resilience import llm_breaker, offline_mode
    circuit = llm_breaker.state()
    llm = "local fallback" if not os.getenv("GROQ_API_KEY") or offline_mode() else "groq" if circuit["status"] != "down" else "groq (unavailable, using built-in fallback)"
    from tools import local_llm
    return {
        "status": "ok",
        "mode": "offline" if offline_mode() else "online",
        "llm": llm,
        "llm_circuit": circuit,
        "local_ai": local_llm.available_model(),
    }


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


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    """Served from the root so it can control the whole app; never cached so updates arrive."""
    return FileResponse(static_dir / "sw.js", media_type="text/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


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
    from tools.resilience import offline_mode
    cloud_ok = not offline_mode()  # OFFLINE_MODE=1 skips the internet voices entirely

    if engine in ("orpheus", "auto") and groq_key and cloud_ok:
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

    # Edge TTS — Microsoft AriaNeural (free, no key), stream directly
    if engine in ("orpheus", "edge", "auto") and cloud_ok:
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

    # Kokoro ONNX — local neural voice
    # The local voice is the last resort for every engine, so speech keeps working with no internet.
    if engine in ("orpheus", "edge", "kokoro", "auto"):
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
                logger.exception("Kokoro TTS failed")

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



def _json_dumps(obj) -> str:
    return _json_lib.dumps(obj, ensure_ascii=False, default=str)


_DATA_EXTENSIONS = {"csv", "xlsx", "xls", "json"}
_DATA_MAX_BYTES = 10 * 1024 * 1024


async def _read_data_upload(file: UploadFile) -> tuple[bytes, str]:
    """Validate type and size, and return (bytes, header-safe filename)."""
    name = file.filename or ""
    ext = name.rsplit(".", 1)[-1].lower()
    if ext not in _DATA_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Unsupported file type. Use CSV, XLSX or JSON.")
    data = await file.read(_DATA_MAX_BYTES + 1)
    if len(data) > _DATA_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large — max 10MB.")
    safe = re.sub(r"[^\w.\-]", "_", Path(name).name)[:100] or f"data.{ext}"
    return data, safe


def _parse_nonempty(parse, data: bytes, name: str):
    df = parse(data, name)
    if len(df) == 0:
        raise ValueError("No data rows found in this file.")
    return df


def _data_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ValueError):
        return HTTPException(status_code=422, detail=str(exc))
    logger.exception("Data processing failed")
    return HTTPException(status_code=422, detail="Could not read this file. Check it is a valid CSV, Excel or JSON file.")


@app.post("/data/profile")
async def data_profile(file: UploadFile = File(...)) -> dict:
    """Upload a CSV/Excel/JSON file and get a data quality profile back."""
    data, name = await _read_data_upload(file)
    from tools.data_cleaner import parse_upload, profile_dataframe

    def work() -> dict:
        return profile_dataframe(_parse_nonempty(parse_upload, data, name))

    try:
        return {"status": "ok", "file": name, "profile": await run_in_threadpool(work)}
    except Exception as exc:
        raise _data_error(exc) from exc


@app.post("/data/clean")
async def data_clean(
    file: UploadFile = File(...),
    mode: str = "clean",  # "clean" | "script" | "report"
    dedupe: bool = True,
) -> Response:
    """
    Clean a CSV/Excel file. mode=clean returns the cleaned file, mode=script a standalone
    Python script, mode=report a JSON list of every change made.
    """
    if mode not in {"clean", "script", "report"}:
        raise HTTPException(status_code=400, detail="mode must be clean, script or report.")
    data, name = await _read_data_upload(file)
    from tools.data_cleaner import clean_with_report, dataframe_to_bytes, generate_cleaning_script, parse_upload

    def work():
        cleaned, report = clean_with_report(_parse_nonempty(parse_upload, data, name), dedupe=dedupe)
        if mode == "report":
            return report, None, None
        out_bytes, media_type = dataframe_to_bytes(cleaned, name)
        return report, out_bytes, media_type

    try:
        if mode == "script":
            script = await run_in_threadpool(generate_cleaning_script, name)
            return Response(content=script, media_type="text/plain", headers={"Content-Disposition": f"attachment; filename=clean_{name}.py"})
        report, out_bytes, media_type = await run_in_threadpool(work)
    except Exception as exc:
        raise _data_error(exc) from exc

    if mode == "report":
        return Response(content=_json_dumps(report), media_type="application/json")
    changes = sum(item["count"] for item in report["summary"])
    return Response(
        content=out_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename=cleaned_{name}",
            "X-Rows-Before": str(report["rows_before"]),
            "X-Rows-After": str(report["rows_after"]),
            "X-Rows-Removed": str(report["rows_before"] - report["rows_after"]),
            "X-Changes-Made": str(changes),
            "X-Issues-Found": str(len(report["summary"]) + len(report["flags"])),
        },
    )


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
            quality = await asyncio.wait_for(
                score_response(
                    user_message=request.message,
                    aria_response=text,
                    escalated=result.get("escalated", False),
                    has_faq_sources=bool(result.get("faq_sources")),
                ),
                timeout=3.0,  # quality scoring must never hold up the answer
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
    if request.language.lower() not in {"python", "datascience"}:
        raise HTTPException(status_code=400, detail="Only Python execution is supported.")
    from tools.e2b_runner import run_python
    result = await asyncio.get_event_loop().run_in_executor(None, lambda: run_python(request.code))
    return result


# ── CODING MENTOR (Java / Spring Boot / Python) ──────────────────────────────
_TUTOR_SLOTS = threading.BoundedSemaphore(int(os.getenv("TUTOR_MAX_CONCURRENT", "4")))
_TUTOR_QUEUE_WAIT = float(os.getenv("TUTOR_QUEUE_WAIT", "0.5"))

from tools.challenges import RateLimiter as _RateLimiter  # noqa: E402

_tutor_limiter = _RateLimiter(limit=30, window=60.0)
_tutor_ip_limiter = _RateLimiter(limit=360, window=60.0)


class TutorRequest(BaseModel):
    language: Literal["python", "java", "spring", "datascience"]
    mode: Literal["explain", "review", "teach", "analyse"] = "explain"
    level: Literal["beginner", "experienced"] = "beginner"
    code: str = Field(default="", max_length=10_000)
    lesson_id: str | None = Field(default=None, max_length=40)
    question: str = Field(default="", max_length=500)
    context: str = Field(default="", max_length=4000)  # dataset summary only, never raw rows


@app.get("/tutor/lessons")
def tutor_lessons(language: Literal["python", "java", "spring", "datascience"], company: dict = Depends(verify_api_key)) -> list[dict]:
    from tools.tutor import lessons_for
    return lessons_for(language)


@app.post("/tutor/stream")
def tutor_stream(request: TutorRequest, http_request: Request, company: dict = Depends(verify_api_key)) -> StreamingResponse:
    """Stream mentor feedback. Learner code is never logged; identical prompts share a cached answer."""
    import json as _json
    from tools.tutor import build_messages, get_lesson, lint_code, offline_for, tutor_events

    _tutor_limiter.limit = int(os.getenv("TUTOR_RATE_LIMIT", "30"))  # requests per browser per minute
    _tutor_ip_limiter.limit = _tutor_limiter.limit * IP_LIMIT_FACTOR
    browser_key, ip_key = _client_keys(http_request, company)
    if not (_tutor_limiter.allow(browser_key) and _tutor_ip_limiter.allow(ip_key)):
        raise HTTPException(status_code=429, detail="You're asking a lot of questions quickly. Please wait a minute and try again.")

    lesson = get_lesson(request.lesson_id, request.language)
    if request.lesson_id and not lesson:
        raise HTTPException(status_code=404, detail="Unknown lesson for this language.")
    if request.mode in {"explain", "review"} and not request.code.strip():
        raise HTTPException(status_code=400, detail="Paste some code first.")
    if request.mode == "teach" and not lesson:
        raise HTTPException(status_code=400, detail="Pick a lesson to be taught.")
    if request.mode == "analyse" and (request.language != "datascience" or not request.context.strip()):
        raise HTTPException(status_code=400, detail="Analyse needs the Data Science track and a dataset summary.")

    findings = lint_code(request.code, request.language) if request.code.strip() else []
    messages = build_messages(
        language=request.language, level=request.level, mode=request.mode, code=request.code,
        lesson=lesson, question=request.question.strip(), findings=findings, context=request.context,
    )
    logger.info("tutor request: mode=%s language=%s level=%s chars=%d", request.mode, request.language, request.level, len(request.code))

    def sse(payload: dict) -> str:
        return f"data: {_json.dumps(payload)}\n\n"

    def offline() -> str:
        return offline_for(
            language=request.language, level=request.level, mode=request.mode, code=request.code,
            lesson=lesson, findings=findings, context=request.context,
        )

    def generate():
        if findings:
            yield sse({"type": "lint", "items": findings})
        # Model slots are taken inside tutor_events, only when the model is actually called, so cache hits and
        # learners waiting on an identical in-flight question never queue; a saturated server sheds to built-in guidance.
        try:
            for event in tutor_events(messages, offline, slots=_TUTOR_SLOTS, slot_wait=_TUTOR_QUEUE_WAIT):
                yield sse(event)
        except Exception:
            logger.exception("Tutor stream failed unexpectedly")
            yield sse({"type": "error", "detail": "Something went wrong. Please try again."})
            return
        yield sse({"type": "done"})

    return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── PRACTICE / INTERVIEW MODE (no LLM, no server-side code execution) ────────
class ChallengeCheckRequest(BaseModel):
    id: str = Field(max_length=20)
    choice: int | None = Field(default=None, ge=0, le=9)
    code: str = Field(default="", max_length=10_000)


class ChallengeSolutionRequest(BaseModel):
    id: str = Field(max_length=20)


IP_LIMIT_FACTOR = 12  # a shared network (a school, a lab) gets this many times one browser's allowance


def _client_keys(request: Request, company: dict) -> tuple[str, str]:
    """(per-browser key, per-network key). Learners on one shared IP are told apart by X-Client-Id."""
    ip = request.client.host if request.client else "unknown"
    browser = re.sub(r"[^A-Za-z0-9-]", "", request.headers.get("x-client-id", ""))[:64]
    owner = company.get("company_id", "anon")
    return f"{owner}:{browser or ip}", f"{owner}:ip:{ip}"


def _rate_limit(request: Request, company: dict) -> None:
    from tools.challenges import ip_limiter, limiter
    browser_key, ip_key = _client_keys(request, company)
    ip_limiter.limit = limiter.limit * IP_LIMIT_FACTOR
    if not (limiter.allow(browser_key) and ip_limiter.allow(ip_key)):
        raise HTTPException(status_code=429, detail="Too many requests. Please wait a minute and try again.")


def _challenge_or_404(challenge_id: str) -> dict:
    from tools.challenges import get
    challenge = get(challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Unknown challenge.")
    return challenge


@app.get("/challenges")
def list_challenges(request: Request, track: Literal["python", "datascience", "java", "spring"], company: dict = Depends(verify_api_key)) -> list[dict]:
    """Prompts, starter code and (for Python/data science) tests. Never answers or solutions."""
    from tools.challenges import list_public
    _rate_limit(request, company)
    return list_public(track)


@app.post("/challenges/check")
def check_challenge(body: ChallengeCheckRequest, request: Request, company: dict = Depends(verify_api_key)) -> dict:
    """Grade a multiple-choice answer or a Java/Spring submission. Static checks only; nothing is executed."""
    from tools.challenges import grade_mcq, grade_rubric
    _rate_limit(request, company)
    challenge = _challenge_or_404(body.id)
    if challenge["type"] == "code":
        raise HTTPException(status_code=400, detail="This challenge is graded in your browser.")
    if challenge["type"] == "mcq":
        if body.choice is None or body.choice >= len(challenge["options"]):
            raise HTTPException(status_code=400, detail="Choose one of the options.")
        return grade_mcq(challenge, body.choice)
    if not body.code.strip():
        raise HTTPException(status_code=400, detail="Write some code first.")
    return grade_rubric(challenge, body.code)


@app.post("/challenges/solution")
def challenge_solution(body: ChallengeSolutionRequest, request: Request, company: dict = Depends(verify_api_key)) -> dict:
    """Reveal the explanation and reference solution (the client applies a score penalty)."""
    from tools.challenges import solution_view
    _rate_limit(request, company)
    return solution_view(_challenge_or_404(body.id))


# ── PHASE 5: CACHE STATS ──────────────────────────────────────────────────────
@app.get("/admin/cache")
def cache_stats(company: dict = Depends(verify_api_key)) -> dict:
    from tools.cache import stats
    return stats()
