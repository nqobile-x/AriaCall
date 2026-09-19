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
