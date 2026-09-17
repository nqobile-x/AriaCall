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
- [x] Conversation memory — 6 turns per session_id
- [x] Voice TTS — Kokoro ONNX local
- [x] Voice STT — Faster-Whisper local
- [x] Knowledge base learning queue
- [x] 4/4 end-to-end tests passing

---

## Recent changes (Claude)

| Date | Change |
|---|---|
| 2026-09-17 | Initial build — LangGraph agent, FastAPI, voice pipeline |
| 2026-09-17 | PII redaction via Presidio on all audit logs |
| 2026-09-17 | Conversation memory (6 turns, in-memory) |
| 2026-09-17 | Fixed FAQ scoring — title hits weighted 3x, normalised by length |
| 2026-09-17 | Comprehensive README, render.yaml, .env.example |

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
