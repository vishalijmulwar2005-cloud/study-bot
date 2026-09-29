"""Pydantic request/response schemas (API contract, Database & API spec §09–§11)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class ApiErrorBody(BaseModel):
    code: str
    message: str


class ApiError(BaseModel):
    error: ApiErrorBody


# ---------- documents ----------


class UploadResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    filename: str
    processing_job_id: uuid.UUID


class DocumentResponse(BaseModel):
    document_id: uuid.UUID
    filename: str
    status: str
    page_count: int | None = None
    error_code: str | None = None
    created_at: str


class DocumentStatusResponse(BaseModel):
    document_id: uuid.UUID
    status: str
    stage: str | None = None
    page_count: int | None = None
    error_code: str | None = None


class DeleteResponse(BaseModel):
    document_id: uuid.UUID
    status: str


# ---------- sessions & messages ----------


class CreateSessionRequest(BaseModel):
    document_id: uuid.UUID


class CreateSessionResponse(BaseModel):
    session_id: uuid.UUID
    document_id: uuid.UUID


class SourceOut(BaseModel):
    chunk_id: uuid.UUID
    page: int
    relevance_score: float


class MessageOut(BaseModel):
    message_id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    status: str
    created_at: str
    sources: list[SourceOut] = []


class MessagesResponse(BaseModel):
    session_id: uuid.UUID
    document_id: uuid.UUID
    messages: list[MessageOut]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AskResponse(BaseModel):
    message_id: uuid.UUID
    answer: str
    grounded: bool
    sources: list[SourceOut]


# ---------- feedback ----------


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    reason: str | None = Field(default=None, max_length=2000)


class FeedbackResponse(BaseModel):
    message_id: uuid.UUID
    rating: str


# ---------- health ----------


class HealthResponse(BaseModel):
    status: str
    database: bool
    rag_configured: bool
