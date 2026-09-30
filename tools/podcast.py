"""Audio Overviews: a two-host podcast about any topic, which the listener can interrupt.

How it works
- The script is written by the cloud model and streamed line by line, so the first line can be
  spoken while the rest is still being written. Hosts: Aria (lead) and Leo (co-host).
- It is grounded in the knowledge base (the same search the chat uses) plus any notes or file the
  listener adds. PulseFlow facts only ever come from those sources.
- The listener can raise a hand at any point: the hosts answer the question in a few lines and
  then pick the episode back up (`answer_lines`).
- Every line is voiced by one of two voices (`synthesize`); the finished episode is joined into a
  single MP3 for download (`build_episode`). Voiced lines are cached, so the download re-uses the
  audio already played instead of paying for it twice.

Fault tolerance mirrors the tutor: model fallbacks, the shared circuit breaker, and a built-in
episode read from the knowledge base when no model is reachable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from collections import OrderedDict
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

from tools.tutor_cache import ResponseCache

logger = logging.getLogger(__name__)

HOSTS = ("aria", "leo")
HOST_NAMES = {"aria": "Aria", "leo": "Leo"}

# Two natural voices per accent. Edge voices are free and need no key; every one returns the same
# MP3 format (24 kHz mono), so the lines of an episode can be joined byte for byte.
EDGE_VOICES = {
    "us": {"aria": "en-US-AriaNeural", "leo": "en-US-AndrewNeural"},
    "za": {"aria": "en-ZA-LeahNeural", "leo": "en-ZA-LukeNeural"},
}
KOKORO_VOICES = {"aria": "af_heart", "leo": "am_michael"}  # local voice used when there is no internet

# target lines, target words, token budget (gpt-oss spends some tokens thinking first)
LENGTHS = {
    "short": {"lines": "10 to 14", "words": 330, "minutes": 2, "max_tokens": 1800},
    "standard": {"lines": "22 to 28", "words": 750, "minutes": 5, "max_tokens": 3200},
    "deep": {"lines": "36 to 44", "words": 1300, "minutes": 9, "max_tokens": 4800},
}

MAX_LINE_CHARS = 420
MAX_SOURCE_CHARS = 1800
MAX_CONTEXT_CHARS = 14_000

script_cache = ResponseCache(max_entries=100)


# ── sources ──────────────────────────────────────────────────────────────────

def gather_sources(topic: str, notes: str = "", company_id: str = "default") -> list[dict]:
    """The listener's own notes first, then knowledge-base matches for the topic."""
    from tools.support_tools import faq_search

    sources: list[dict] = []
    if notes.strip():
        sources.append({"title": "Your notes", "text": notes.strip()[:8000]})
    try:
        from tools.rag import rag_search
        sources.extend(rag_search(topic, company_id=company_id, top_k=4))
    except Exception:  # noqa: BLE001 - the vector store is optional
        pass
    sources.extend(faq_search(topic))

    seen: set[str] = set()
    unique: list[dict] = []
    total = 0
    for source in sources:
        title = str(source.get("title") or "Document").strip()
        text = str(source.get("text") or "").strip()
        key = (title + text[:80]).lower()
        if not text or key in seen:
            continue
        seen.add(key)
        limit = 8000 if title == "Your notes" else MAX_SOURCE_CHARS
        text = text[:limit]
        if total + len(text) > MAX_CONTEXT_CHARS:
            break
        total += len(text)
        unique.append({"title": title, "text": text})
    return unique


def _sources_block(sources: list[dict]) -> str:
    if not sources:
        return "No sources matched. Use accurate general knowledge, and do not invent anything about PulseFlow."
    return "\n\n".join(f"[{i + 1}] {s['title']}\n{s['text']}" for i, s in enumerate(sources))


# ── prompts ──────────────────────────────────────────────────────────────────

_RULES = (
    "Write ONLY dialogue lines, one per line, each starting with ARIA: or LEO: and nothing else. "
    "No titles, no markdown, no stage directions, no sound effects, no emojis. "
    "Inside the dialogue, write the hosts' names normally (Aria, Leo), never in capitals. "
    "Keep every line to one to three spoken sentences. Write for the ear: short sentences, contractions, "
    "numbers written the way people say them. "
    "Facts about PulseFlow (plans, prices, billing, policies, features) must come only from the sources; "
    "never invent them. For general topics, be accurate and say so plainly when something is uncertain."
)


def build_script_messages(topic: str, sources: list[dict], length: str) -> list[dict]:
    spec = LENGTHS.get(length, LENGTHS["standard"])
    system = (
        "You write Aria Overviews: warm, lively two-host audio episodes that explain one topic clearly. "
        "ARIA is the lead host: clear, knowledgeable, practical. LEO is the curious co-host: asks the questions "
        "a listener would ask, reacts, sums up, and adds analogies. They build on each other naturally, "
        "the way two friends explain something over coffee, without talking down to the listener. "
        "Open with a quick hook and say what the episode covers, go deep on what matters most, give one "
        "concrete example, and close with a short recap of the key takeaways. "
        + _RULES
    )
    user = (
        f"Topic: {topic}\n"
        f"Length: {spec['lines']} lines, about {spec['words']} words in total (roughly {spec['minutes']} minutes).\n\n"
        f"Sources:\n{_sources_block(sources)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def build_answer_messages(topic: str, question: str, recent: list[dict], sources: list[dict]) -> list[dict]:
    system = (
        "You are the two hosts of an Aria Overview episode, and a listener has just interrupted with a question. "
        "Reply in 2 to 4 lines. The first line (by LEO) says a listener has jumped in and repeats their question, "
        "ARIA answers it directly and accurately, and the last line (by LEO) briefly steers back to the episode. "
        "If the sources do not cover a PulseFlow question, ARIA says so and suggests asking support in chat. "
        + _RULES
    )
    so_far = "\n".join(f"{HOST_NAMES.get(l['speaker'], 'Aria').upper()}: {l['text']}" for l in recent[-6:])
    user = (
        f"Episode topic: {topic}\n\n"
        f"What the hosts were just saying:\n{so_far or '(the episode had just started)'}\n\n"
        f"Listener's question: {question}\n\n"
        f"Sources:\n{_sources_block(sources)}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ── parsing ──────────────────────────────────────────────────────────────────

_LINE_RE = re.compile(r"^\W*(ARIA|LEO)\W*\s*:\s*(.*)$", re.IGNORECASE)


def clean_text(text: str) -> str:
    """Strip anything a voice would read out literally: markdown, stage directions, emojis."""
    text = re.sub(r"\[[^\]]*\]|\((?:laughs?|chuckles?|pauses?|sighs?|music|intro|outro)[^)]*\)", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"[*_#`~>|]+", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _split_long(speaker: str, text: str) -> list[dict]:
    if len(text) <= MAX_LINE_CHARS:
        return [{"speaker": speaker, "text": text}]
    parts, current = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if current and len(current) + len(sentence) + 1 > MAX_LINE_CHARS:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return [{"speaker": speaker, "text": p[:MAX_LINE_CHARS]} for p in parts]


class ScriptParser:
    """Turns streamed model text into complete dialogue lines.

    A line is only released once the next speaker starts (or the stream ends), because a model
    sometimes wraps one speaker's turn over several physical lines.
    """

    def __init__(self) -> None:
        self.buffer = ""
        self.pending: dict | None = None

    def feed(self, text: str) -> list[dict]:
        self.buffer += text
        out: list[dict] = []
        while "\n" in self.buffer:
            raw, self.buffer = self.buffer.split("\n", 1)
            out.extend(self._take(raw))
        return out

    def flush(self) -> list[dict]:
        out = self._take(self.buffer)
        self.buffer = ""
        if self.pending:
            out.extend(self._release())
        return out

    def _take(self, raw: str) -> list[dict]:
        if not raw.strip():
            return []
        match = _LINE_RE.match(raw)
        if match:
            out = self._release()
            self.pending = {"speaker": match.group(1).lower(), "text": match.group(2)}
            return out
        if self.pending:  # continuation of the current speaker's turn
            self.pending["text"] += " " + raw
        return []

    def _release(self) -> list[dict]:
        pending, self.pending = self.pending, None
        if not pending:
            return []
        text = clean_text(pending["text"])
        return _split_long(pending["speaker"], text) if text else []


def parse_script(text: str) -> list[dict]:
    parser = ScriptParser()
    return parser.feed(text) + parser.flush()


# ── model calls ──────────────────────────────────────────────────────────────

def _request_options(model: str, max_tokens: int) -> dict:
    options = {"model": model, "temperature": 0.8, "max_tokens": max_tokens}
    if model.startswith("openai/gpt-oss"):
        options["reasoning_effort"] = "low"  # a script needs little planning; keep the budget for dialogue
    return options


def _stream_model(messages: list[dict], model: str, max_tokens: int) -> Iterator[str]:
    import httpx
    from groq import Groq

    client = Groq(timeout=httpx.Timeout(45.0, connect=5.0), max_retries=0)
    stream = client.chat.completions.create(messages=messages, stream=True, **_request_options(model, max_tokens))
    for chunk in stream:
        delta = chunk.choices[0].delta.content if chunk.choices else None
        if delta:
            yield delta


def _complete_model(messages: list[dict], model: str, max_tokens: int) -> str:
    import httpx
    from groq import Groq

    client = Groq(timeout=httpx.Timeout(25.0, connect=5.0), max_retries=0)
    completion = client.chat.completions.create(messages=messages, **_request_options(model, max_tokens))
    return completion.choices[0].message.content or ""


def _cloud_unavailable_reason() -> str | None:
    from tools.resilience import llm_breaker, offline_mode

    if offline_mode():
        return "Offline mode is on, so this is a short built-in overview read from the knowledge base."
    if not os.getenv("GROQ_API_KEY"):
        return "The online AI isn't configured, so this is a short built-in overview read from the knowledge base."
    if not llm_breaker.allow():
        return "The online AI is having trouble, so this is a short built-in overview read from the knowledge base."
    return None


def _scrub(exc: Exception) -> str:
    return re.sub(r"(?i)(gsk_|sk-|bearer\s+)[\w\-.]+", r"\g<1>***", f"{type(exc).__name__}: {str(exc)[:120]}")


def script_events(topic: str, notes: str = "", length: str = "standard", company_id: str = "default") -> Iterator[dict]:
    """Yield {'type': 'sources'|'line'|'notice'} events for a new episode. Never raises."""
    from tools.resilience import AUTH, NETWORK, TRANSIENT, classify_error, llm_breaker
    from tools.tutor import model_chain

    sources = gather_sources(topic, notes, company_id)
    yield {"type": "sources", "items": [s["title"] for s in sources]}

    messages = build_script_messages(topic, sources, length)
    cache_key = script_cache.key(messages)
    cached = script_cache.get(cache_key)
    if cached is not None:
        for line in json.loads(cached):
            yield {"type": "line", **line}
        return

    reason = _cloud_unavailable_reason()
    if reason:
        yield {"type": "notice", "text": reason}
        yield from ({"type": "line", **line} for line in offline_script(topic, sources))
        return

    max_tokens = LENGTHS.get(length, LENGTHS["standard"])["max_tokens"]
    last_error = ""
    key_rejected = False
    for model in model_chain():
        if key_rejected:
            break
        for attempt in range(2):
            parser = ScriptParser()
            lines: list[dict] = []
            try:
                for token in _stream_model(messages, model, max_tokens):
                    for line in parser.feed(token):
                        lines.append(line)
                        yield {"type": "line", **line}
                for line in parser.flush():
                    lines.append(line)
                    yield {"type": "line", **line}
                if len(lines) < 4:
                    raise ValueError(f"model returned {len(lines)} usable lines")
                llm_breaker.record_success()
                script_cache.set(cache_key, json.dumps(lines))
                return
            except Exception as exc:  # noqa: BLE001 - every provider failure must degrade, not crash
                kind = classify_error(exc)
                last_error = _scrub(exc)
                logger.warning("Podcast model %s failed (%s, attempt %d): %s", model, kind, attempt + 1, last_error)
                if lines:  # the listener already has part of the episode: finish it honestly
                    llm_breaker.record_failure(last_error)
                    for line in parser.flush():  # keep the last line only if it was finished, not cut mid-sentence
                        if line["text"][-1:] in ".!?\"'”’":
                            yield {"type": "line", **line}
                    yield {"type": "notice", "text": "The connection dropped part-way, so this episode ends early."}
                    yield {"type": "line", "speaker": "aria", "text": "We'll have to leave it there for now. Thanks for listening!"}
                    return
                if kind == AUTH:
                    llm_breaker.trip("API key rejected: " + last_error)
                    key_rejected = True
                    break
                if kind == NETWORK:
                    llm_breaker.record_failure(last_error)
                    yield {"type": "notice", "text": "No internet connection to the online AI, so this is a short built-in overview."}
                    yield from ({"type": "line", **line} for line in offline_script(topic, sources))
                    return
                if kind == TRANSIENT and attempt == 0:
                    continue
                break
    if not key_rejected:
        llm_breaker.record_failure(last_error)
    yield {"type": "notice", "text": "The online AI is unavailable right now, so this is a short built-in overview."}
    yield from ({"type": "line", **line} for line in offline_script(topic, sources))


def answer_lines(topic: str, question: str, recent: list[dict], notes: str = "", company_id: str = "default") -> dict:
    """The hosts' reply to a listener's question: {'lines': [...], 'notice': str | None}."""
    from tools.resilience import AUTH, TRANSIENT, classify_error, llm_breaker
    from tools.tutor import model_chain

    sources = gather_sources(f"{question} {topic}", notes, company_id)
    reason = _cloud_unavailable_reason()
    if not reason:
        messages = build_answer_messages(topic, question, recent, sources)
        for model in model_chain():
            for attempt in range(2):
                try:
                    lines = parse_script(_complete_model(messages, model, 1200))
                    if lines:
                        llm_breaker.record_success()
                        return {"lines": lines[:6], "notice": None}
                    break
                except Exception as exc:  # noqa: BLE001
                    kind = classify_error(exc)
                    logger.warning("Podcast answer model %s failed (%s): %s", model, kind, _scrub(exc))
                    if kind == AUTH:
                        llm_breaker.trip("API key rejected")
                        return {"lines": offline_answer(question, sources), "notice": "The online AI is unavailable, so this answer comes straight from the knowledge base."}
                    if kind == TRANSIENT and attempt == 0:
                        continue
                    llm_breaker.record_failure(_scrub(exc))
                    break
        reason = "The online AI is unavailable, so this answer comes straight from the knowledge base."
    return {"lines": offline_answer(question, sources), "notice": reason}


# ── built-in episodes (no model) ─────────────────────────────────────────────

def _sentences(text: str) -> list[str]:
    text = clean_text(re.sub(r"^---.*?---\s*", "", text, flags=re.DOTALL))
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) > 3]


def offline_script(topic: str, sources: list[dict]) -> list[dict]:
    """A short, honest episode read from the knowledge base. Nothing is invented."""
    lines = [
        {"speaker": "aria", "text": f"Welcome to Aria Overviews. Today we're looking at {clean_text(topic)[:120]}."},
    ]
    kb = [s for s in sources if _sentences(s["text"])][:3]
    if not kb:
        lines += [
            {"speaker": "leo", "text": "So, what do we have on this one?"},
            {"speaker": "aria", "text": "Honestly, nothing in the knowledge base yet, and the online AI isn't available right now, so I don't want to guess."},
            {"speaker": "leo", "text": "Fair enough. Try again in a little while, or add your own notes and we'll talk you through them."},
        ]
        return lines
    lines.append({"speaker": "leo", "text": "Great. Walk me through it. What's the first thing people should know?"})
    prompts = ["Got it. What else should people know?", "That's useful. Anything else worth knowing?"]
    for index, source in enumerate(kb):
        sentences = _sentences(source["text"])
        first, rest = " ".join(sentences[:2]), " ".join(sentences[2:4])
        lines.extend(_split_long("aria", f"This comes from {source['title']}. {first}"))
        if rest:
            lines.append({"speaker": "leo", "text": "Okay, and then?"})
            lines.extend(_split_long("aria", rest))
        if index < len(kb) - 1:
            lines.append({"speaker": "leo", "text": prompts[index % len(prompts)]})
    lines += [
        {"speaker": "leo", "text": "That's a handy overview. Where can people go if they need more?"},
        {"speaker": "aria", "text": "Just ask me in chat, and if it needs a person, I'll hand you over to the team. Thanks for listening!"},
    ]
    return lines


def offline_answer(question: str, sources: list[dict]) -> list[dict]:
    kb = [s for s in sources if s["title"] != "Your notes" and _sentences(s["text"])]
    lines = [{"speaker": "leo", "text": f"Quick question from you: {clean_text(question)[:200]}"}]
    if kb:
        lines.extend(_split_long("aria", f"Good one. According to {kb[0]['title']}: {' '.join(_sentences(kb[0]['text'])[:3])}"))
    else:
        lines.append({"speaker": "aria", "text": "I don't have that in the knowledge base, so I won't guess. Ask me in chat and I'll find you the right answer or a person who knows."})
    lines.append({"speaker": "leo", "text": "Right, back to where we were."})
    return lines


# ── voices ───────────────────────────────────────────────────────────────────

class AudioCache:
    """Recently voiced lines, bounded by total size, so the download re-uses what was played."""

    def __init__(self, max_bytes: int = 48 * 1024 * 1024) -> None:
        self.max_bytes = max_bytes
        self._data: OrderedDict[tuple, tuple[bytes, str]] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()

    def get(self, key: tuple) -> tuple[bytes, str] | None:
        with self._lock:
            item = self._data.get(key)
            if item:
                self._data.move_to_end(key)
            return item

    def set(self, key: tuple, audio: bytes, media_type: str) -> None:
        with self._lock:
            if key in self._data:
                return
            self._data[key] = (audio, media_type)
            self._size += len(audio)
            while self._size > self.max_bytes and self._data:
                _, (old, _) = self._data.popitem(last=False)
                self._size -= len(old)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._size = 0


audio_cache = AudioCache()


async def _edge_audio(text: str, voice: str) -> bytes:
    import edge_tts

    audio = bytearray()
    async for chunk in edge_tts.Communicate(text, voice=voice, rate="+4%").stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    if not audio:
        raise RuntimeError("edge voice returned no audio")
    return bytes(audio)


def _kokoro_ready() -> bool:
    model = Path("voice/models/kokoro-v1.0.onnx")
    return model.exists() and model.stat().st_size >= 100_000_000 and Path("voice/models/voices-v1.0.bin").exists()


def _kokoro_audio(text: str, speaker: str) -> bytes:
    import soundfile as sf

    from api.app import kokoro_engine

    audio, rate = kokoro_engine().create(text, voice=KOKORO_VOICES[speaker], speed=1.03, lang="en-us")
    buffer = BytesIO()
    sf.write(buffer, audio, rate, format="WAV")
    return buffer.getvalue()


async def synthesize(text: str, speaker: str, accent: str = "us", engine: str = "auto") -> tuple[bytes, str]:
    """Voice one line. engine: 'auto' (online voice, local fallback), 'edge' or 'kokoro'."""
    from tools.resilience import offline_mode

    speaker = speaker if speaker in HOSTS else "aria"
    accent = accent if accent in EDGE_VOICES else "us"
    if engine in ("auto", "edge") and not offline_mode():
        key = ("edge", EDGE_VOICES[accent][speaker], text)
        cached = audio_cache.get(key)
        if cached:
            return cached
        try:
            audio = await asyncio.wait_for(_edge_audio(text, key[1]), timeout=25)
            audio_cache.set(key, audio, "audio/mpeg")
            return audio, "audio/mpeg"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Podcast edge voice failed: %s", type(exc).__name__)
            if engine == "edge":
                raise
    if engine in ("auto", "kokoro") and _kokoro_ready():
        key = ("kokoro", KOKORO_VOICES[speaker], text)
        cached = audio_cache.get(key)
        if cached:
            return cached
        audio = await asyncio.to_thread(_kokoro_audio, text, speaker)
        audio_cache.set(key, audio, "audio/wav")
        return audio, "audio/wav"
    raise RuntimeError("no podcast voice available")


def _join_wavs(parts: list[bytes]) -> bytes:
    import numpy as np
    import soundfile as sf

    arrays, rate = [], 24000
    for part in parts:
        data, rate = sf.read(BytesIO(part), dtype="float32")
        arrays.append(data)
        arrays.append(np.zeros(int(rate * 0.25), dtype="float32"))  # a breath between speakers
    buffer = BytesIO()
    sf.write(buffer, np.concatenate(arrays), rate, format="WAV")
    return buffer.getvalue()


async def build_episode(lines: list[dict], accent: str = "us", concurrency: int = 4) -> tuple[bytes, str]:
    """One audio file for the whole episode: MP3 when the online voices work, WAV from the local voice otherwise."""
    gate = asyncio.Semaphore(concurrency)

    async def voice_all(engine: str) -> list[bytes]:
        async def one(line: dict) -> bytes:
            async with gate:
                audio, _ = await synthesize(line["text"], line["speaker"], accent, engine=engine)
                return audio
        return await asyncio.gather(*(one(line) for line in lines))

    from tools.resilience import offline_mode

    if not offline_mode():
        try:
            # Edge MP3 frames carry no container header, so the lines join into one valid file.
            return b"".join(await voice_all("edge")), "audio/mpeg"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Podcast download: online voice failed (%s), trying the local voice", type(exc).__name__)
    if _kokoro_ready():
        parts = await voice_all("kokoro")
        return await asyncio.to_thread(_join_wavs, parts), "audio/wav"
    raise RuntimeError("no podcast voice available")
