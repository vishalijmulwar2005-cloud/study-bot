-- 0001_initial.sql — PDF & Notes Q&A Chatbot
-- Mirrors the Database & API Specification §04–§06.
-- NOTE: {EMBEDDING_DIM} is substituted by the migration runner from the
--       EMBEDDING_DIM environment setting. It MUST match your embedding
--       provider's output dimension (OpenAI text-embedding-3-small: 1536,
--       Gemini text-embedding-004: 768, Gemini gemini-embedding-001: 3072).
--       Changing the model later requires a fresh database or a new migration.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY,
    email       VARCHAR(320) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
    id          UUID PRIMARY KEY,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    -- Anonymous MVP owner reference: SHA-256 hex of the session cookie token.
    session_id  VARCHAR(64),
    filename    VARCHAR(512) NOT NULL,
    mime_type   VARCHAR(128) NOT NULL,
    size_bytes  BIGINT NOT NULL,
    storage_key TEXT NOT NULL,
    page_count  INTEGER,
    status      VARCHAR(16) NOT NULL DEFAULT 'UPLOADED'
                CHECK (status IN ('UPLOADED','PROCESSING','READY','FAILED','DELETING','DELETED')),
    error_code  VARCHAR(64),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Spec §06: index documents by owner/session and status.
CREATE INDEX IF NOT EXISTS ix_documents_session ON documents (session_id);
CREATE INDEX IF NOT EXISTS ix_documents_status  ON documents (status);
CREATE INDEX IF NOT EXISTS ix_documents_user    ON documents (user_id);

CREATE TABLE IF NOT EXISTS processing_jobs (
    id          UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    status      VARCHAR(16) NOT NULL DEFAULT 'QUEUED'
                CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED')),
    stage       VARCHAR(16) NOT NULL DEFAULT 'QUEUED'
                CHECK (stage IN ('QUEUED','EXTRACT','CHUNK','EMBED','INDEX','DONE')),
    error_code  VARCHAR(64),
    started_at  TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Spec §06: index processing_jobs by document_id and status.
CREATE INDEX IF NOT EXISTS ix_jobs_document ON processing_jobs (document_id);
CREATE INDEX IF NOT EXISTS ix_jobs_status   ON processing_jobs (status);

CREATE TABLE IF NOT EXISTS document_chunks (
    id           UUID PRIMARY KEY,
    document_id  UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index  INTEGER NOT NULL,
    page_start   INTEGER NOT NULL,
    page_end     INTEGER NOT NULL,
    section      VARCHAR(256),
    text         TEXT NOT NULL,
    token_count  INTEGER,
    embedding    vector({EMBEDDING_DIM}) NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Spec §06: unique constraint on (document_id, chunk_index).
    CONSTRAINT uq_chunk_index UNIQUE (document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS ix_chunks_document ON document_chunks (document_id);

-- Spec §06: vector index matching the cosine distance metric (see docs/DECISIONS.md).
CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw
    ON document_chunks USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE TABLE IF NOT EXISTS sessions (
    id          UUID PRIMARY KEY,
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    session_id  VARCHAR(64),
    status      VARCHAR(16) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','ARCHIVED')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_sessions_document ON sessions (document_id);
CREATE INDEX IF NOT EXISTS ix_sessions_owner    ON sessions (session_id);

CREATE TABLE IF NOT EXISTS messages (
    id          UUID PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        VARCHAR(16) NOT NULL CHECK (role IN ('USER','ASSISTANT')),
    content     TEXT NOT NULL,
    status      VARCHAR(16) NOT NULL DEFAULT 'COMPLETE'
                CHECK (status IN ('COMPLETE','NO_EVIDENCE','ERROR')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Spec §06: index messages by session_id and created_at.
CREATE INDEX IF NOT EXISTS ix_messages_session ON messages (session_id, created_at);

CREATE TABLE IF NOT EXISTS message_sources (
    id              UUID PRIMARY KEY,
    message_id      UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    chunk_id        UUID NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    page            INTEGER NOT NULL,
    relevance_score REAL NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Spec §06: index message_sources by message_id and chunk_id.
CREATE INDEX IF NOT EXISTS ix_sources_message ON message_sources (message_id);
CREATE INDEX IF NOT EXISTS ix_sources_chunk   ON message_sources (chunk_id);

CREATE TABLE IF NOT EXISTS feedback (
    id          UUID PRIMARY KEY,
    message_id  UUID NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    rating      VARCHAR(8) NOT NULL CHECK (rating IN ('up','down')),
    reason      TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_feedback_message ON feedback (message_id);
