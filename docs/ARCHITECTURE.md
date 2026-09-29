# Project Structure — PDF & Notes Q&A Chatbot

One page to find where everything lives. Specification traceability (PRD →
TRD → UI/UX → App Flow) is in §6; open implementation decisions are in
[DECISIONS.md](DECISIONS.md).

## 1. Repository tree

```
.
├── docker-compose.yml          # Postgres 16 + pgvector only (db service)
├── .env.example                # every config variable, documented
├── devdb/
│   └── server.mjs              # dev-only PostgreSQL (PGlite WASM + pgvector)
│                               # behind real wire protocol on 127.0.0.1:5432
│                               # — used when Docker is unavailable
├── docs/
│   ├── DECISIONS.md            # all decisions the specs left open (#1…#12)
│   └── ARCHITECTURE.md         # this file
├── backend/                    # FastAPI (Python 3.10+)
│   ├── .env                    # local config (never committed)
│   ├── pytest.ini
│   ├── requirements.txt
│   ├── migrations/
│   │   ├── run_migrations.py   # reads EMBEDDING_DIM → vector column
│   │   └── versions/
│   ├── scripts/
│   │   └── reindex_document.py # ops: rebuild chunks+vectors for one doc
│   ├── storage/                # private PDF binaries (never served statically)
│   ├── tests/                  # unit + integration/security suite
│   └── app/
│       ├── main.py             # app factory: logging, CORS, error handlers,
│       │                       # routers, /api/v1/health, worker lifecycle
│       ├── bundle.py           # ServiceBundle — dependency wiring
│       ├── config.py           # Settings (pydantic-settings, .env)
│       ├── database.py         # engine/session, ORM models, check_database()
│       ├── models.py           # enums + document lifecycle state machine
│       ├── schemas.py          # Pydantic request/response models
│       ├── api/                # HTTP layer (thin: validate → authorize → call service)
│       │   ├── deps.py         # identity + ownership dependencies
│       │   ├── documents.py    # upload / status / retry / delete
│       │   ├── sessions.py     # create session, list + ask messages
│       │   └── feedback.py     # rate an answer (up/down)
│       ├── core/               # cross-cutting
│       │   ├── errors.py       # AppError, ErrorCode, stable {error:{code,message}}
│       │   ├── security.py     # anonymous HttpOnly cookie, SHA-256 token hash,
│       │   │                   # IdentityCookieMiddleware, ownership checks
│       │   ├── logging.py      # correlation IDs, privacy-minimized log events
│       │   ├── rate_limit.py   # in-memory per-process limits (MVP)
│       │   └── filenames.py    # safe filename sanitization
│       └── services/           # domain logic (no HTTP concerns)
│           ├── storage.py      # LocalFileStorage (put/load/delete, StorageError)
│           ├── pdf_processor.py# page extraction + header/footer stripping
│           ├── chunker.py      # ~450-token chunks, 60 overlap, page ranges
│           ├── embeddings.py   # OpenAI-compatible /embeddings client
│           ├── llm.py          # OpenAI-compatible chat-completions client
│           ├── prompts.py      # grounded-answer system/user prompt builder
│           ├── retriever.py    # evaluate_evidence gate, NO_EVIDENCE_ANSWER
│           ├── vector_store.py # pgvector queries — always document-scoped
│           ├── source_validator.py # chunk metadata → validated page sources
│           ├── chat_pipeline.py# ask_question orchestration (Flow 11)
│           └── worker.py       # DB-backed job queue, in-process poller
├── frontend/                   # React 18 + Vite 6 + TypeScript + Tailwind 3
│   ├── vite.config.ts          # /api → :8000 same-origin proxy in dev
│   └── src/
│       ├── App.tsx             # Sidebar + AppShell, polling hook
│       ├── main.tsx
│       ├── types.ts            # ChatPhase, Message, DocumentMeta
│       ├── api/client.ts       # typed fetch wrapper, ApiClientError (stable codes)
│       ├── store/useAppStore.ts# zustand: upload + chat state machines
│       ├── hooks/
│       │   └── useDocumentPolling.ts # status polling → applyStatusUpdate
│       └── components/
│           ├── AppShell.tsx    # layout: upload ↔ chat switch
│           ├── Sidebar.tsx     # active document + New chat
│           ├── UploadZone.tsx  # drag & drop, client-side pre-validation
│           ├── DocumentCard.tsx# filename, status, retry / delete actions
│           ├── StatusBadge.tsx # UPLOADED→PROCESSING→READY/FAILED
│           ├── ChatWindow.tsx  # message list, phase banners
│           ├── MessageBubble.tsx # markdown answer, copy action
│           ├── SourceChip.tsx  # "Page 12" chips (server-validated only)
│           ├── Composer.tsx    # question input, disabled until READY
│           ├── SuggestedPrompt.tsx
│           ├── ErrorState.tsx  # retry / replace recovery actions
│           └── LoadingState.tsx
└── e2e/                        # Playwright end-to-end suite
    ├── playwright.config.ts
    ├── helpers/
    └── tests/
```

## 2. Runtime topology

```
Browser (React SPA, :5173)
   │  same-origin /api/v1  (Vite proxy in dev; CORS_ORIGINS for direct use)
   ▼
FastAPI (:8000) ── IdentityCookieMiddleware (anonymous session, HttpOnly)
   │  ├─ Rate limiter (in-memory)
   │  ├─ Error handlers → {error:{code,message}}
   │  ├─ Routers: documents / sessions / feedback
   │  └─ ProcessingWorker (asyncio poller inside the API process)
   ▼
PostgreSQL + pgvector (:5432)
   ├─ docker compose (pgvector/pgvector:pg16) — preferred
   └─ devdb/server.mjs (PGlite WASM) — Docker-less dev fallback
External providers (OpenAI-compatible):
   ├─ Embeddings (gemini-embedding-001 @ 768d in current setup)
   └─ Chat LLM (openai/gpt-oss-20b via NVIDIA NIM in current setup)
```

Trust boundary: **the active uploaded PDF.** Vector queries always carry
`WHERE document_id = :doc`; the evidence gate decides deterministically
whether the LLM runs; sources are attached from retrieval metadata, never
from model output.

## 3. Document lifecycle (worker pipeline)

State machine in `backend/app/models.py` (spec §07):

```
UPLOADED → PROCESSING → READY | FAILED
READY    → DELETING | PROCESSING (re-index)
FAILED   → PROCESSING (retry) | DELETING
DELETING → DELETED (terminal)
```

Worker job (`backend/app/services/worker.py`), claimed once via
`FOR UPDATE SKIP LOCKED`:

```
QUEUED → EXTRACT (PDF → pages, furniture stripped)
       → CHUNK   (~450 tokens, 60 overlap, page ranges, section)
       → EMBED   (batched, provider-side)
       → INDEX   (replace_document_chunks + READY in ONE transaction)
       → DONE
```

Failure contract: job + document → FAILED with a **safe code**
(`INVALID_PDF`, `OCR_UNAVAILABLE`, `EMPTY_DOCUMENT`, `STORAGE_UNAVAILABLE`,
`EMBEDDING_NOT_CONFIGURED`, `INTERNAL_ERROR`); exception text never reaches
the client. Retry is idempotent (chunks replaced transactionally).

## 4. Chat flow (Flow 11) — `chat_pipeline.ask_question`

```
authorize (cookie identity) → session↔document check → document READY
→ persist USER message → load history (last 6 turns)
→ document-scoped vector search (top_k=5)
→ evidence gate (cosine ≥ EVIDENCE_THRESHOLD)
   ├─ insufficient + short anaphoric follow-up → ONE deterministic retry
   │   with reformulated query (prev question + current + answer excerpt)
   ├─ insufficient → persist NO_EVIDENCE assistant message, NO LLM call
   └─ sufficient → LLM (grounded prompt) → validate sources vs. document
       → persist ASSISTANT message + message_sources (chunk, page, score)
```

Hard rules: the LLM never decides whether evidence exists; if the model
echoes the no-evidence answer, grounded=false and sources are dropped;
cross-owner access returns 404 (existence hidden).

## 5. Frontend state machines (`useAppStore.ts`)

```
Document: IDLE → DRAG_OVER → UPLOADING → PROCESSING → SUCCESS | ERROR
          (INVALID = client pre-validation; ERROR offers retry/replace)
Chat:     IDLE → SUBMITTING → RETRIEVING → GENERATING → COMPLETE
                                        ↘ NO_EVIDENCE | ERROR
```

- New upload resets session + messages (App Flow 08 — scope change).
- `newChat()` clears conversation, keeps the active document.
- Delete clears everything only after backend confirms cleanup.
- Polling (`useDocumentPolling`) drives PROCESSING → SUCCESS/ERROR with
  worker stage labels; composer unlocks on READY only.

## 6. Spec traceability (App Flow key points → code)

| # | Key point | Where it lives |
|---|---|---|
| 1 | Purpose / scope | [README.md](../README.md), [DECISIONS.md](DECISIONS.md) |
| 2 | Core user flow (upload→ready→ask→source→follow-up) | `UploadZone` → `useDocumentPolling` → `Composer`/`ChatWindow` |
| 3 | System master flow (extract→chunk→embed→index→READY) | `backend/app/services/worker.py` |
| 4 | PRD→TRD→UI/UX traceability | [README.md](../README.md) + [DECISIONS.md](DECISIONS.md) |
| 5 | Acceptance scenarios | `backend/tests/` (integration, state machine, follow-up, PDF validation, retrieval) + `e2e/tests` |
| 6 | Product flow diagram | [README.md](../README.md) §Architecture |
| 7 | Backend workflow (Flow 11) | `backend/app/services/chat_pipeline.py` |
| 8 | Frontend workflow (Flow 12) | `frontend/src/components/AppShell.tsx` + `frontend/src/store/useAppStore.ts` |
| 9 | Evidence gate (LLM is not a fallback) | `retriever.evaluate_evidence` + `chat_pipeline` (NO_EVIDENCE branch) |
| 10 | Answer rendering + page source chips | `MessageBubble.tsx`, `SourceChip.tsx` (server-validated `message_sources`) |
| 11 | Follow-up handling (scoped, pronoun resolution) | `chat_pipeline` B-2 reformulation (`is_dependent_followup`, `build_reformulated_query`) |
| 12 | PDF change / new chat / delete cleanup | `useAppStore.uploadDocument/newChat/removeDocument`; backend `DELETE_DEPENDENT_CHAT` workflow |
| 13 | Failure & recovery (upload reject, OCR, storage, LLM, timeouts) | `core/errors.py` ErrorCode taxonomy; worker failure contract; `ErrorState.tsx` + `DocumentCard` retry |

## 7. Configuration & secrets

Single source: environment (`.env` → `backend/app/config.py`, see
[.env.example](../.env.example)). No secrets in code. Model-dependent knobs:
`EMBEDDING_DIM` (768 for gemini-embedding-001) must match the DB column —
run migrations on a fresh DB after changing it; `EVIDENCE_THRESHOLD` 0.48
for Gemini embeddings (~0.25 for OpenAI).

## 8. Runbook

```bash
# DB (either)
docker compose up -d db                 # real Postgres + pgvector
# …or, without Docker:
cd devdb && npm install && node server.mjs   # WASM Postgres on :5432

# Backend
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
copy ..\.env.example .env               # fill provider keys
.venv/Scripts/python -m migrations.run_migrations
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev    # :5173, proxies /api → :8000

# Tests
cd backend && .venv/Scripts/python -m pytest tests --ignore=tests/test_integration.py
cd frontend && npm run typecheck && npm run build
cd e2e && npx playwright test           # optional, full stack
```

Current machine note: Docker is unavailable here — the stack runs with
`devdb` (node on :5432) + uvicorn on :8000 + Vite on :5173.
