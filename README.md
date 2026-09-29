# PDF & Notes Q&A Chatbot

A document-grounded study assistant: upload a PDF, and ask questions that are
answered **only** from that document's content, with page-level source
references. When the document doesn't contain the answer, the assistant says
so instead of inventing one.

Implemented from the connected specification series (PRD v1.0, TRD v1.0,
UI/UX, App Flow, Security & Privacy 05A, Database & API 05B).
Implementation decisions for everything the specs left open are recorded in
[docs/DECISIONS.md](docs/DECISIONS.md).

## Architecture

```
React + Vite + Tailwind (chat UI)
    ↓  /api/v1  (same-origin proxy in dev)
FastAPI (validation, orchestration, authorization)
    ├── LocalFileStorage (private PDF binaries)
    ├── PostgreSQL + pgvector (documents, chunks+vectors, sessions, messages, sources)
    └── Background worker (DB-backed job queue)
          PDF extract → chunk (+page metadata) → embed → index → READY
    Retrieval: document-scoped vector search → evidence gate → LLM
```

Trust boundary: **the active uploaded PDF.** Every vector query carries
`WHERE document_id = :doc`; the evidence gate decides deterministically
whether the LLM is called at all; sources are attached server-side from
retrieval metadata, never from model output.

## Prerequisites

- Python 3.10+ (backend)
- Node 18+ (frontend)
- PostgreSQL **with the pgvector extension** — easiest via the provided
  compose file (Docker Desktop), or any existing Postgres 14+ where you can
  `CREATE EXTENSION vector`.
- An LLM + embedding provider (see below). **The app starts and serves the UI
  without credentials, but uploads will fail with `EMBEDDING_NOT_CONFIGURED`
  and chat returns 503 until both providers are configured.** This is by
  design — there is no mock RAG path.

## Quick start

```bash
# 1) Database (Postgres + pgvector)
docker compose up -d db

# 2) Backend
cd backend
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt        # Windows
# source .venv/bin/activate && pip install -r requirements.txt   # macOS/Linux

# configure
copy ..\.env.example .env        # then edit .env (provider keys!)
#   on macOS/Linux: cp ../.env.example .env

# apply migrations (creates tables; vector column uses EMBEDDING_DIM)
.venv\Scripts\python -m migrations.run_migrations

# run
.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000

# 3) Frontend (new terminal)
cd frontend
npm install
npm run dev          # http://localhost:5173  (proxies /api → :8000)
```

Open http://localhost:5173, upload a PDF, wait for **Ready**, ask questions.

### Provider configuration (the only required secrets)

The LLM and embedding services are **OpenAI-compatible abstractions**
(`LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`). Any compatible endpoint works:

**Option A — OpenAI**
```
LLM_API_KEY=sk-...                 EMBEDDING_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini              EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_DIM=1536
```

**Option B — Gemini embeddings + NVIDIA NIM chat (current setup).** Google
exposes an OpenAI-compatible endpoint for embeddings; NVIDIA NIM provides the
chat model:
```
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_API_KEY=<NVIDIA_API_KEY>
LLM_MODEL=openai/gpt-oss-20b        # or nvidia/nemotron-3-super-120b-a12b

EMBEDDING_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
EMBEDDING_API_KEY=<GEMINI_API_KEY>
EMBEDDING_MODEL=gemini-embedding-001
EMBEDDING_DIM=768
EMBEDDING_DIMENSIONS=768
EVIDENCE_THRESHOLD=0.48
```
⚠️ `EMBEDDING_DIM` must match the embedding model **and** the database
column. The migration runner reads it, so after changing it, run migrations
against a **fresh** database (drop/recreate or change `DATABASE_URL` db name).
⚠️ `EVIDENCE_THRESHOLD` is model-dependent: Gemini embeddings need ~0.48
(measured: unrelated questions score 0.42–0.47, on-topic 0.50+ once repeated
page headers/footers are stripped); OpenAI embeddings work at ~0.25.

## No Docker? Dev database without installation

If Docker/PostgreSQL is unavailable on the machine, `devdb/server.mjs` runs a
**development-only** PostgreSQL (WASM via PGlite) with pgvector built in,
behind a real PG wire protocol on `127.0.0.1:5432`:

```bash
cd devdb && npm install && node server.mjs
```

It is single-user — keep the single-connection pool settings in `backend/.env`
(`DB_POOL_SIZE=1`, `DB_MAX_OVERFLOW=0`, `DB_POOL_PRE_PING=false`). For
production, use real PostgreSQL + pgvector (docker compose or managed).

## RAG configuration (documented, model-dependent)

| Parameter | Value | Why |
|---|---|---|
| LLM | `openai/gpt-oss-20b` via NVIDIA NIM (`integrate.api.nvidia.com/v1`) | Gemini chat quota exhausted on the free tier; NIM's OpenAI-compatible endpoint works with the same code path. `nvidia/nemotron-3-super-120b-a12b` is a tested alternative |
| Embedding model | `gemini-embedding-001` via `dimensions: 768` (Gemini endpoint) | 768-dim vectors keep the DB column lean |
| Similarity metric | cosine (`1 - embedding <=> query`) | pgvector `vector_cosine_ops` HNSW index |
| `EVIDENCE_THRESHOLD` | **0.48 for Gemini embeddings** (0.25 for OpenAI `text-embedding-3-*`) | Measured live with header/footer stripping: unrelated questions 0.42–0.47, on-topic 0.50–0.67. The earlier 0.55 rejected legitimate on-topic questions — see docs/DECISIONS.md #12 |
| `RETRIEVAL_TOP_K` | 5 | candidate chunks per question before the gate |
| Follow-up retrieval | deterministic reformulation fallback | short anaphoric questions ("Explain that in simple words") retry retrieval with `previous question + current question (+ prior answer excerpt)`; threshold, document scope, and the deterministic gate are unchanged — the LLM never decides whether evidence exists |

## Tests

```bash
# backend — always runnable
cd backend
.venv\Scripts\python -m pytest tests --ignore=tests/test_integration.py

# backend — integration + security suite (needs Postgres; create the DB first)
#   e.g. docker compose exec db createdb -U postgres pdf_qa_test
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pdf_qa_test \
  .venv\Scripts\python -m pytest tests/test_integration.py

# frontend
cd frontend
npm run typecheck && npm run build

# E2E (optional; needs full stack + Playwright browsers)
cd e2e && npm install && npx playwright install && npx playwright test
```

## API (canonical /api/v1)

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/v1/documents` | Upload PDF (multipart). Authoritative server-side validation. |
| GET | `/api/v1/documents/{id}` | Document metadata + status. |
| GET | `/api/v1/documents/{id}/status` | Processing status + stage. |
| POST | `/api/v1/documents/{id}/retry` | Re-queue a FAILED document (idempotent). |
| DELETE | `/api/v1/documents/{id}` | Full deletion workflow (idempotent). |
| POST | `/api/v1/sessions` | Create a chat session scoped to a READY document. |
| GET | `/api/v1/sessions/{id}/messages` | Ordered conversation. |
| POST | `/api/v1/sessions/{id}/messages` | Ask a question → grounded answer + sources. |
| POST | `/api/v1/messages/{id}/feedback` | Rate an answer (up/down). |
| GET | `/api/v1/health` | `{status, database, rag_configured}`. |

Interactive OpenAPI docs: http://localhost:8000/api/docs

Errors use the stable contract `{"error": {"code", "message"}}` with codes
`INVALID_REQUEST / UNAUTHENTICATED / FORBIDDEN / NOT_FOUND / FILE_TOO_LARGE /
UNSUPPORTED_MEDIA / INVALID_PDF / RATE_LIMITED / INTERNAL_ERROR /
SERVICE_UNAVAILABLE`. Internal details never reach the client.

## Identity model (MVP)

Anonymous, server-issued session token in an **HttpOnly + SameSite=Lax
cookie**; only its SHA-256 hash is stored. Every document-scoped request
re-verifies ownership server-side — cross-owner access returns 404
(existence hidden). Production authentication is an open PRD decision
(docs/DECISIONS.md #7).

## Configuration

See [.env.example](.env.example) — every variable is documented there
(limits, RAG parameters, rate limits, retention switch, provider endpoints).
No secrets are hardcoded; production secrets must never be committed.

## Known limitations (MVP)

- OCR is **not** implemented; scanned/image-only PDFs fail with a clear
  `OCR_UNAVAILABLE` message (documented failure path).
- Rate limiting is in-memory per process (single-process MVP).
- The processing worker runs in the API process (DB-backed queue); swap for
  Celery/RQ at scale without changing job semantics.
- Chat history lives with its document (deleted together); persistent
  cross-session history is out of MVP scope.
- No page-preview on source chips (open product decision).
