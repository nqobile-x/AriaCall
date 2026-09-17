# Aria Support Agent

Text-only customer-support prototype powered by LangGraph. It includes customer lookup, account checks, FAQ retrieval, ticket creation, escalation rules, response drafting, and an Obsidian-compatible Markdown audit trail. Twilio and PII/Paste Gate functionality are intentionally excluded.

## Run

```powershell
.\\venv\\Scripts\\uvicorn main:app --reload
```

Send a request to `POST /support`:

```json
{"customer_id":"demo-001","message":"I forgot my password"}
```

Open `http://127.0.0.1:8000/docs` to try it interactively.

Open `http://127.0.0.1:8000/` for the Aria chat interface. Voice mode uses local Faster-Whisper transcription and local Kokoro neural speech after a one-time model download.

Run the end-to-end checks with:

```powershell
.\\venv\\Scripts\\python.exe -m unittest tests.test_system -v
```

## Notes and optional free API

Interaction notes are stored in `obsidian-vault/Aria Support/Interactions` by default. In `.env`, set `OBSIDIAN_VAULT` to your actual vault path to have them appear in Obsidian immediately.

## Grounded knowledge base

Put product, policy, and FAQ notes in `Aria Support/Knowledge Base` inside the vault. LangChain loads and chunks those Markdown notes; the agent retrieves the best matching chunks for each message, uses them as its RAG context, and returns their title in the response. It falls back to the included starter FAQs only when the folder is empty. The optional Groq prompt is constrained to that retrieved context, so it will not make up a policy.

Aria also has a built-in capability record, so it can explain its own support tools even when your vault has no matching note. Add Markdown notes to the vault to teach it product-specific policies, processes, and answers—this is grounded knowledge-base training, not irreversible model fine-tuning.

When no knowledge-base note answers a message, Aria writes a proposed note to `Aria Support/Knowledge Base/Review Queue`. Review and complete its proposed answer, then move it into the Knowledge Base folder to make it searchable. Aria never promotes notes by itself.

Architecture: **LangGraph** orchestrates the support workflow, while **LangChain** handles knowledge-base documents and chunks. This works locally now and can later swap to a vector retriever when the vault grows.

If you add a free Groq API key as `GROQ_API_KEY`, the agent uses the free Llama model to draft FAQ-based replies. Without it, it uses a local response template.
