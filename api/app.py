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


@app.post("/voice", responses={200: {"content": {"audio/wav": {}}}})
def voice(request: VoiceRequest) -> Response:
    model = Path("voice/models/kokoro-v1.0.onnx")
    voices = Path("voice/models/voices-v1.0.bin")
    if not model.exists() or model.stat().st_size < 100_000_000 or not voices.exists():
        raise HTTPException(status_code=503, detail="Kokoro's local model is still downloading.")
    try:
        import soundfile as sf
        audio, sample_rate = kokoro_engine().create(request.text, voice="af_heart", speed=1.03, lang="en-us")
        buffer = BytesIO()
        sf.write(buffer, audio, sample_rate, format="WAV")
        return Response(content=buffer.getvalue(), media_type="audio/wav")
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Kokoro could not create speech.") from exc


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
