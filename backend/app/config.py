"""Application configuration.

All runtime configuration comes from environment variables (see .env.example).
No secrets are hardcoded anywhere in the codebase.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthMode(str, Enum):
    ANONYMOUS = "anonymous"
    AUTHENTICATED = "authenticated"  # not implemented in MVP; rejected at startup


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Application
    app_env: str = "development"
    cors_origins: str = "http://localhost:5173"
    log_level: str = "INFO"
    auth_mode: AuthMode = AuthMode.ANONYMOUS

    # Database
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/pdf_qa"
    # TLS mode for PostgreSQL connections. Local/dev Postgres runs without TLS;
    # managed providers (Render, Neon, Supabase) require SSL — set
    # DB_SSLMODE=require there.
    db_sslmode: str = "disable"
    # Connection pool tuning. The dev WASM database (devdb/server.mjs) is
    # single-user: set DB_POOL_SIZE=1, DB_MAX_OVERFLOW=0, DB_POOL_PRE_PING=false
    # for it (see README). Production PostgreSQL keeps the defaults.
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True

    # Upload limits
    max_upload_mb: int = 25
    max_pdf_pages: int = 300

    # Storage
    storage_dir: str = "storage"
    delete_dependent_chat: str = "delete"  # "delete" | "retain"
    # Optional: directory holding the built React frontend (index.html +
    # assets/) to serve from this process. Empty = API only (local dev, where
    # the Vite dev server serves the UI with its /api proxy).
    static_dir: str = ""

    # Embedding provider (OpenAI-compatible)
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    # Optional `dimensions` request parameter (supported by Gemini's
    # OpenAI-compatible endpoint, e.g. 768 for gemini-embedding-001).
    # When set, it MUST equal embedding_dim.
    embedding_dimensions: int | None = None
    embedding_batch_size: int = 64

    # LLM provider (OpenAI-compatible)
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: int = 60
    llm_max_output_tokens: int = 1024

    # RAG parameters
    retrieval_top_k: int = Field(default=5, ge=1)
    evidence_threshold: float = Field(default=0.25, ge=0.0, le=1.0)
    chunk_target_tokens: int = Field(default=450, ge=50)
    chunk_overlap_tokens: int = Field(default=60, ge=0)

    # Rate limiting
    rate_limit_upload_per_min: int = 10
    rate_limit_chat_per_min: int = 20
    rate_limit_status_per_min: int = 120
    rate_limit_window_seconds: int = 60

    @field_validator("auth_mode")
    @classmethod
    def _check_auth_mode(cls, value: AuthMode) -> AuthMode:
        if value is AuthMode.AUTHENTICATED:
            # User accounts are an open PRD decision and out of MVP scope.
            raise ValueError(
                "AUTH_MODE=authenticated is not implemented in the MVP; use 'anonymous'."
            )
        return value

    @field_validator("embedding_dimensions")
    @classmethod
    def _check_embedding_dimensions(cls, value: int | None, info) -> int | None:
        # Fail fast at startup on a mismatch that would otherwise surface as a
        # generic processing failure when the provider returns a different dim.
        dim = info.data.get("embedding_dim")
        if value is not None and dim is not None and value != dim:
            raise ValueError(
                f"EMBEDDING_DIMENSIONS ({value}) must equal EMBEDDING_DIM ({dim})."
            )
        return value

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def rag_configured(self) -> bool:
        """True when embedding + LLM providers are configured for the RAG path."""
        return bool(self.embedding_api_key) and bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
