from __future__ import annotations

import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agents.support_agent import SupportAgent

load_dotenv()
app = FastAPI(title="Aria Support Agent", version="0.1.0")
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


class TranscriptionResponse(BaseModel):
    text: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "llm": "groq" if os.getenv("GROQ_API_KEY") else "local fallback"}


@app.get("/debug-groq")
def debug_groq() -> dict:
    key = os.getenv("GROQ_API_KEY", "")
    if not key:
        return {"error": "GROQ_API_KEY not set", "key_preview": None}
    try:
        from groq import Groq
        completion = Groq(api_key=key, timeout=10.0).chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": "Say hi"}],
            max_tokens=10,
        )
        return {"status": "ok", "response": completion.choices[0].message.content, "key_preview": key[:8] + "..."}
    except Exception as exc:
        return {"error": type(exc).__name__, "detail": str(exc), "key_preview": key[:8] + "..."}


@app.get("/", include_in_schema=False)
def interface() -> FileResponse:
    return FileResponse(static_dir / "index.html")


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
    # 1. Edge TTS — Microsoft neural voice "Aria" (free, no API key needed)
    try:
        import asyncio
        import edge_tts
        communicate = edge_tts.Communicate(request.text, voice="en-US-AriaNeural", rate="+5%", pitch="+0Hz")
        buffer = BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                buffer.write(chunk["data"])
        if buffer.tell() > 0:
            return Response(content=buffer.getvalue(), media_type="audio/mpeg")
    except Exception:
        pass  # fall through to Kokoro

    # 2. Kokoro ONNX — local neural voice (needs model files on disk)
    model = Path("voice/models/kokoro-v1.0.onnx")
    voices = Path("voice/models/voices-v1.0.bin")
    if model.exists() and model.stat().st_size >= 100_000_000 and voices.exists():
        try:
            import soundfile as sf
            audio, sample_rate = kokoro_engine().create(request.text, voice="af_heart", speed=1.03, lang="en-us")
            buffer = BytesIO()
            sf.write(buffer, audio, sample_rate, format="WAV")
            return Response(content=buffer.getvalue(), media_type="audio/wav")
        except Exception:
            pass

    # 3. No TTS available — browser falls back to speechSynthesis
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


@app.post("/support", response_model=SupportResponse)
def support(request: SupportRequest) -> SupportResponse:
    try:
        result = agent.handle(
            message=request.message,
            customer_id=request.customer_id,
            conversation_id=request.conversation_id or str(uuid4()),
        )
        return SupportResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
