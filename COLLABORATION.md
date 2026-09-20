# Aria — Agent Collaboration Reference

This file is the shared source of truth for Claude Code and ChatGPT working on this project.
Edit it when architecture changes, new features land, or blockers arise.

---

## Architecture (current)

```
Browser UI  ──►  FastAPI (main.py / api/app.py)
                      │
              LangGraph SupportAgent (agents/support_agent.py)
                      │
     ┌────────────────┼────────────────────┐
     ▼                ▼                    ▼
customer_lookup   faq_search         escalation_trigger
account_status    (LangChain RAG)    create_ticket
                      │
                 draft_response
                 (Groq Llama IF key set)
                      │
                 _redact_pii (Presidio)
                      │
                 log_interaction → Obsidian Markdown
```

Voice pipeline (separate from agent workflow):
- `/transcribe` — Faster-Whisper base.en (local CPU)
- `/voice`      — Kokoro ONNX af_heart (local CPU)

---

## Key files

| File | Owner | Purpose |
|---|---|---|
| `agents/support_agent.py` | Claude | LangGraph workflow + conversation memory |
| `tools/support_tools.py` | Claude | All tool functions (lookup, FAQ, escalate, log) |
| `api/app.py` | Claude | FastAPI routes |
| `api/static/index.html` | ChatGPT | Chat UI |
| `api/static/app.js` | ChatGPT | Frontend logic (voice, submit, TTS playback) |
| `api/static/styles.css` | ChatGPT | Styling |
| `api/static/aria-mark.svg` | ChatGPT | Logo |
| `main.py` | Claude | Entry point |
| `render.yaml` | Claude | Render deploy config |

---

## Vault location

Aria's runtime data lives **outside** this repo:

```
C:\Users\nqobile\Desktop\OBSIDIAN\Nqobz\AriaCall\
└── Aria Support\
    ├── Knowledge Base\     ← add .md notes here to train Aria
    │   ├── password-reset.md
    │   ├── billing-details.md
    │   └── Review Queue\   ← Aria proposes notes here
    └── Interactions\       ← PII-redacted audit logs
```

Set in `.env`:
```
OBSIDIAN_VAULT=C:\Users\nqobile\Desktop\OBSIDIAN\Nqobz\AriaCall
```

---

## Verified features

- [x] Customer lookup by ID or email
- [x] Account status check
- [x] FAQ retrieval — weighted title/body scoring, normalised by doc length
- [x] Escalation — keyword detection (fraud, charged twice, legal, etc.)
- [x] Ticket creation with ARIA-XXXXXXXX IDs
- [x] PII redaction (Presidio) before audit log write
- [x] Conversation memory — 6 turns per session_id, keyed by conversation_id
- [x] Voice TTS — Kokoro ONNX local (198KB WAV verified)
- [x] Voice STT — Faster-Whisper local
- [x] Knowledge base learning queue
- [x] Persistent conversation_id via localStorage — audit records group correctly
- [x] "New Chat" button — fresh UUID, clears UI and ticket banner
- [x] "Talk to a human" visible button — triggers escalation workflow
- [x] Ticket banner — shows ARIA-XXXXXXXX on escalation in the UI
- [x] 4/4 end-to-end tests passing (verified on combined codebase)

---

## Recent changes (Claude)

| Date | Change |
|---|---|
| 2026-09-17 | Initial build — LangGraph agent, FastAPI, voice pipeline |
| 2026-09-17 | PII redaction via Presidio on all audit logs |
| 2026-09-17 | Conversation memory (6 turns, in-memory) |
| 2026-09-17 | Fixed FAQ scoring — title hits weighted 3x, normalised by length |
| 2026-09-17 | Comprehensive README, render.yaml, .env.example |

## Recent changes (ChatGPT)

| Date | Change |
|---|---|
| 2026-09-17 | Persistent `conversation_id` in localStorage — groups audit logs across refreshes |
| 2026-09-17 | "New Chat" button — resets UUID, clears conversation + ticket banner |
| 2026-09-17 | "Talk to a human" button — visible escalation trigger in suggestions |
| 2026-09-17 | Ticket banner — shows ticket ID on escalation in fixed position UI |
| 2026-09-17 | Voice UX: silence detection, one tap to record |
| 2026-09-17 | Verified combined suite: 4/4 tests passing |
| 2026-09-19 | UI audit: replaced wizard/composer emoji controls with custom SVG icons; voice-call panel now supports minimise, restore, and expanded states without altering the Aria wave animation |

## Coordination note — user direction

- The user deploys with **Render**. Do not remove, replace, or reconfigure Render, the deployed voice model, or backend behaviour without explicit approval.
- ChatGPT reverted exploratory backend, model-path, test, and voice-selector changes made during an audit. The requested UI-only icon/call-panel changes remain; the Aria wave animation is untouched.

## Handoff to Claude — 2026-09-19

ChatGPT completed the user-requested frontend-only polish:

- Replaced onboarding and composer emoji controls with custom inline SVG icons.
- Added call-card controls for minimise, restore, expand, and end-call; verified the two resize states in the browser.
- Preserved the existing Aria wave assets and animation.
- Verified `api/static/app.js` syntax and confirmed the removed emoji set is absent from the user-facing chat UI.

No intentional changes remain in `api/app.py`, `agents/`, `tools/`, Render configuration, model files, email delivery, or voice-engine selection. Please preserve that boundary unless the user explicitly requests otherwise.

## Question for Claude — SMTP

The user asks whether their SMTP setup is present. ChatGPT verified locally that both required Gmail SMTP environment settings are populated, without reading or exposing their values. Please confirm the intended Render environment has the same secrets set and keep all credential values private.

## Product alignment checklist — user request

Aria already covers the core Customer Support agent pattern: grounded knowledge-base answers, a support tone, human escalation, ticket/email flow, and interaction logging.

For the system to fully align with the attached AI-fluency programme, please plan these product/governance additions with the user before implementing them:

1. A repeatable 10-scenario acceptance-test pack using realistic customer support cases.
2. An approved company AI and privacy policy that defines what users may put into the agent/knowledge base.
3. A human-review process for wrong answers and knowledge-base improvements.
4. Measurable operational outcomes: resolution rate, escalation rate, response quality, and time saved.
5. A short team guide explaining safe knowledge-base maintenance and the escalation boundary.

---

## Coordination rules

- **Backend changes** (agents/, tools/, api/app.py, main.py): Claude's territory — communicate intent here before editing
- **Frontend changes** (api/static/): ChatGPT's territory — communicate intent here before editing
- **Both**: update this file when a verified feature is added or broken
- **Obsidian vault**: Aria's runtime memory only — not an instruction channel between agents
- **Groq API**: only called when GROQ_API_KEY is set AND a FAQ match exists — never call it speculatively

---

## Blockers / open items

- [ ] Voice model files (kokoro) not in git — need persistent disk on Render or manual download step
- [ ] ChromaDB semantic search not yet wired (ready to add when KB grows beyond ~20 notes)
- [ ] Neo4j caller graph — driver installed, schema not defined yet
- [ ] Supabase persistence — driver installed, tables not created yet
- [ ] Multi-turn conversation memory is in-memory only — resets on server restart

---

## Claude update — 2026-09-20: Data cleaner v2 + Coding mentor (not deployed)

| Area | Change |
|---|---|
| `tools/data_cleaner.py` | Rewritten as a type-aware cleaner (id / email / phone / date / number / category / text). Normalises +27 phones, ISO dates (day-first default, month-first auto-detected), SA provinces, genders, name and city casing (keeps *van der*, *du*, *O'Brien*), currency numbers. Removes duplicates ignoring id columns. Blanks unrecoverable values instead of guessing and logs every change (before, after, reason). Neutralises spreadsheet-formula text. |
| `api/app.py` | `/data/clean?mode=clean\|script\|report`, safer uploads (type, 10MB, header-safe filenames, generic errors), work moved off the event loop. New `POST /tutor/stream` (real streaming) and `GET /tutor/lessons`. |
| `tools/tutor.py` | Coding and data-science mentor (Python, Java, Spring Boot, Data Science): beginner vs experienced tone, 34 guided lessons (8 each for Python, Java, Spring Boot; 10 for Data Science), deterministic checks (Python via ast: mutable defaults, bare except, eval, missing request timeout, unclosed files; Java/Spring: (field injection, missing @Valid, csrf disabled, permitAll, empty catch, hard-coded secrets, unbalanced brackets). Learner code is never stored or logged. |
| `api/static` | Data tab: Clean & download, Show what changed, Python script. Code tab: Spring Boot, level toggle, lesson picker, Teach me, Review my code, safe markdown rendering. Code tab no longer goes through the support/escalation pipeline. |
| Tests | `tests/test_data_cleaner.py`, `tests/test_tutor.py` — 101 tests pass (`python -m unittest discover tests`). |

### Alignment with the AI Fluency programme

| Programme principle | Where it shows up |
|---|---|
| Human-in-the-loop / "AI can be wrong, always review" | Mentor ends every answer with a run-it-and-check-the-docs reminder; cleaner blanks rather than guesses and produces a change report to review; Jev scores support answers. |
| Data privacy / nothing sensitive into AI tools | Tutor does not persist or log code; warns when code contains a credential; PII redacted in support audit logs. |
| Testing and improving an agent (10 scenarios) | Automated tests plus lesson set; **still to do:** the 10-scenario acceptance pack (checklist item 1). |
| Knowledge base and instructions | Tutor persona is a versioned system prompt in `tools/tutor.py`. |

### Known limits
- Spring Boot code is reviewed, not executed (no JVM sandbox). Python still runs via E2B.
- Phone rules assume +27; other countries' `+` numbers are kept unchanged. Dates default to day-first.
- No per-user rate limit on `/tutor/stream` yet (4 concurrent model calls max).
- Aria's answers to non-support questions are unverified model output; the lesson content should be reviewed by a person before students rely on it.

### Data-science track (added 2026-09-20)
- `tools/tutor_datascience.py`: 10 lessons (question framing, pandas, cleaning, EDA, honest charts, statistics, SQL, first ML model, evaluation, storytelling) and AST checks for data leakage (fit before split), missing `random_state`, `inplace=True`, chained assignment, `iterrows`, removed `DataFrame.append`, truncated bar-chart axes and accuracy-only evaluation.
- Persona rules: start from the decision, baseline first, quantify uncertainty, separate correlation from causation, **never invent numbers or dataset facts**.
- Data tab: **Ask the data scientist** sends column names, types and counts only (never row values) and returns quality concerns, questions worth asking and an analysis plan.
- `tools/e2b_runner.py`: stdout from `print()` is now captured in the E2B sandbox (it previously only returned expression results; unverified without an `E2B_API_KEY`), and code that imports libraries gets a clear message when no sandbox key is set.
- Known: `tests/test_changes.py` sets `GROQ_API_KEY=fake` at import, so `unittest discover` logs one harmless 401 from the fallback path.

### Fault tolerance — 2026-09-20
**Question asked:** if the AI API fails, can the system keep working on its own?

| Feature | Without the AI API |
|---|---|
| Data cleaning, profiling, change report, generated script | Works fully (pure Python, no API) |
| Automated code checks (Python, Java, Spring, data science) | Works fully |
| Coding mentor | Degrades: retry, fallback models, then **built-in offline tutor** (lesson goal, starter code, TODOs, automated findings, structure summary, checklist, official docs) clearly labelled "Offline mode" |
| Support chat | Answers from the knowledge base; escalation, tickets and email are rule-based and unaffected |
| Quality scoring (Jev) | Capped at 3s so it can never delay an answer |
| Voice | Already falls back Orpheus → Edge → Kokoro |
| Running code | E2B sandbox; without a key only plain Python runs, with a clear message otherwise |

How it works (`tools/resilience.py`, `tools/tutor.py`, `tools/tutor_offline.py`):
1. Errors are classified: transient (timeout, 429, 5xx) → retry once; model rejected (400/404) → next model; credentials rejected (401/403) → stop immediately, retrying cannot help.
2. Fallback chain `TUTOR_MODEL` → `TUTOR_FALLBACK_MODELS` (default `llama-3.3-70b-versatile,llama-3.1-8b-instant`).
3. A shared circuit breaker (3 failures → open for 60s, one probe to recover) so an outage costs ~0.4s instead of a timeout per request. Chat and tutor share it.
4. `/health` now reports `llm_circuit`; the UI header shows "AI limited — built-in mode" and a notice above tutor answers.
5. A mid-stream drop keeps the partial answer and warns that it may be incomplete. Provider error text is logged with key-like strings redacted and is never sent to the browser.

Measured with a deliberately invalid key: tutor answered in 1.9s (0.4s once the breaker opened), support chat still answered from the KB, data cleaning unaffected (40 → 36 rows).

Still depends on external services (all optional, with fallbacks): Neo4j (~2s per chat call when reachable; skipped if not), Pinecone (not installed here; keyword search is used), Gmail OAuth for emails (a failure appends "couldn't send a confirmation email" instead of crashing). **Not covered:** a total Render outage, and the offline tutor cannot give a personalised line-by-line explanation — that needs the model.

### Practice / mock-interview mode — 2026-09-20
**Question asked:** a technical-interview / CoderByte-style mode for data science, Python, Java and Spring Boot that says what is right or wrong, needs no API key, and does not overwhelm Render.

| Track | Grading | API key? | Render load |
|---|---|---|---|
| Python, Data Science | Real code execution against tests in the **learner's browser** (Pyodide in a Web Worker, 12s hard limit on the learner's code) | No | None: the interpreter and pandas come from a CDN |
| Java, Spring Boot | **Static rubric** (regex checks on code with comments and strings stripped) plus quizzes | No | A few regexes per submit, 10k-character cap |

- **Files:** `tools/challenge_bank.py` (35 challenges: 11 Python, 11 Data Science, 8 Java, 9 Spring), `tools/challenges.py` (grading, rate limiter), `api/static/challenge_harness.py` (shared test harness), `api/static/practice.js` (Practice tab), endpoints `GET /challenges`, `POST /challenges/check`, `POST /challenges/solution`.
- **Modes:** free practice (hints, show solution, "Ask Aria why" which works offline too) and a 30-minute mock interview (5 mixed-difficulty questions, hints cost 25% each, solutions locked, summary with per-question breakdown and a link to the matching lessons).
- **Scoring:** partial credit per test/check passed; the unchanged starter code always scores 0.
- **Quality gate (`tests/test_challenges.py`):** every reference solution passes all tests, every starter fails, no answers or solutions leak from `/challenges`, comments/strings cannot fake a Java pass, and the endpoints are rate-limited (429) and work with no LLM key.
- **Honest limits:** Java/Spring are not executed (there is no JVM on Render and running strangers' Java there would be heavy and unsafe), so passing shows correct structure, not correct behaviour. Python tests ship to the browser, so a determined learner can read them: this is practice, not a proctored exam. The first Python run downloads the Python engine, about 12 MB in total including pandas and numpy (measured with `scripts/fetch_offline_assets.py --dry-run`), and it is then cached; on mobile data that still matters.


### Can the whole system work offline? — 2026-09-20
**Short answer:** yes for a local install, partly for a cloud deployment. It was measured, not assumed: the real server was run with every non-loopback network connection blocked, and the browser was tested with the server stopped.

| Capability | Server has no internet | Browser has no server (after one visit) |
|---|---|---|
| App pages, data cleaning, change report, generated script | Works | Pages load; cleaning needs the server |
| Python and Data Science practice + grading | Works | **Works** (Pyodide + tests cached by the service worker) |
| Java, Spring, quizzes | Works | Needs the server (friendly message) |
| Coding mentor | **Local AI** (Ollama) if running, else built-in guidance | Needs the server |
| Support chat | KB answers, rule-based escalation and tickets | Needs the server |
| Voice | **Local Kokoro** for every engine choice | Needs the server |
| Ticket email, Jev scoring, Neo4j memory | Skipped fast, no waiting | n/a |

What was added:
1. `OFFLINE_MODE=1` skips every cloud call up front (Groq, Neo4j, Jev, Gmail, cloud voices); without it, a dead network is detected on the first failure (classified `network`, so the remaining cloud models are not tried) and a circuit breaker remembers it.
2. `tools/local_llm.py`: the mentor falls back to a local Ollama model (`OLLAMA_MODEL`, `LOCAL_LLM_URL`, `LOCAL_LLM=off` to disable). Measured with `qwen3:0.6b`: works with the internet cut, first answer in about 24s on CPU. It is small: it found the right bug but wrote a wrong fix, so answers are labelled and the automated checks stay the anchor. A larger model (for example a 3-4B coder model) would be markedly better; that is a download the user decides on. Support-chat wording deliberately does not use a small local model (risk of invented policy); chat answers from the knowledge base.
3. Voice: orpheus/edge/auto now fall back to local Kokoro instead of returning 503.
4. Neo4j: 3s connection timeout and a 90s failure memory (previously every request retried the connection).
5. Frontend: `api/static/sw.js` (served at `/sw.js`) caches the app shell, challenge/lesson lists and the Python engine; header pill shows "Offline mode", "AI limited — local model" or "Server unreachable"; friendly messages instead of raw errors.
6. `scripts/fetch_offline_assets.py` downloads the Python engine (12 MB with pandas/numpy, SHA-256 verified) into a git-ignored folder so a local install needs no CDN at all. Run with `--dry-run` first.

To run fully offline on a laptop: `OFFLINE_MODE=1`, run `python scripts/fetch_offline_assets.py` once while online, keep Ollama running, and the Kokoro model files in `voice/models/`.

Not possible offline, by nature: the cloud Groq model, cloud voices, Gmail, Neo4j graph memory, and a cloud (Render) deployment when Render itself is unreachable. Also not covered: the admin page and landing page still reference Google Fonts/highlight.js CDNs (they degrade to system fonts / plain code), and Kokoro speech takes 2-6s on CPU.

### UI redesign, voice listen-along and the floating voice panel — 2026-09-20
**Problems fixed (measured at phone size before the change):** the page was 784px tall so the message box sat below the fold; the composer reserved 158px for absolutely-positioned buttons with 28px input text; 9-11px text in a colour that failed contrast; four tabs plus three actions crammed in the header with one breakpoint; inline styles everywhere; no focus rings; a `<style>` block outside `<head>`; a blocking web-font `@import`.

**What it is now**
- `styles.css` rewritten as one design system (tokens, buttons, segmented controls, cards, fields). App fills the viewport (`100dvh`); the header and message box are always on screen and each region scrolls inside itself. Phones get a bottom tab bar; the Code panel stacks below 900px; controls grow to 44px on touch; hover effects only where hover exists; secondary text is 6.6:1 contrast; nothing under 11px.
- Accessibility: real `tablist` with `aria-selected` and arrow keys, focus rings, labelled controls, keyboard-operable rows and dropzone, a dialog for PDF export (Esc closes), toast instead of `alert()`, closed call panel no longer focusable.
- Fixed while testing: the lesson list was empty until a language was toggled; a numbered heading was read as a lone "one".
- **Listen-along** (`api/static/voice.js`): every answer in Code, Data and Practice gets a listen bar (Listen/Pause/Stop, speed, voice, "Read answers aloud"). The sentence being read is highlighted in green and the current word in orange (CSS Custom Highlight API, so the DOM is never touched; block highlight fallback). Code blocks are announced, not read.
- **Ask by voice → floating voice panel:** opens from Code, Data and Practice. Shows what Aria hears (live), "thinking" with your question, and the sentence being read. Drag it by mouse, touch or arrow keys; minimise to a pill (tap to expand, Esc to minimise); position, minimised state and "Keep the conversation going" (hands-free: Aria listens again after she finishes) are remembered. Closes when you leave the section; the microphone is never open while Aria speaks.
- All speech runs in the browser (Web Speech API): **zero server or API cost**. Speech recognition in Chrome uses the browser vendor's service, so it needs internet; reading aloud works offline with a local voice.

**Protecting the API and Render** (measured with `scratchpad/load_test.py`: 40 concurrent aggressive learners for 25s, simulated model with 1.5s latency)
- 814 tutor requests caused **16 model calls** (cache + single-flight: identical in-flight questions share one call); 11% were served built-in guidance because all slots were busy at the start (32% before the fixes).
- Memory 82 → 89 MB; `/health` max 65ms under load; static/challenge endpoints p95 about 20ms.
- Concurrency slots are taken only when the model is actually called, so cache hits and followers never queue; a saturated server sheds to built-in guidance in ≤0.5s instead of piling up threads.
- Rate limits are per browser (`X-Client-Id`) with a 12× looser per-network cap, so a class behind one school IP is not throttled as one person and rotating ids cannot bypass it. Tunable without a redeploy: `TUTOR_RATE_LIMIT`, `TUTOR_MAX_CONCURRENT`, `TUTOR_QUEUE_WAIT`, `TUTOR_MAX_WAITERS`, `TUTOR_FLIGHT_WAIT`, `TUTOR_CACHE=off`.
- The answer cache is in memory only (300 entries, 6h), keyed by a hash of the whole prompt; only complete cloud answers are stored.

**Not verified:** the real microphone (the browser pane blocks it, so a fake recogniser was used for the spoken question; everything after that was real), real Render hardware, and speech on iOS Safari. Speech voices and quality differ by browser and device.
