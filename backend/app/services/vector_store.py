"""VectorStore abstraction + pgvector implementation (Phases 3, 7).

CRITICAL RETRIEVAL RULE (Security §06, TRD §5.2 — the single most important
implementation rule in this system):

    Every vector query is scoped to the active document. The WHERE
    document_id = :doc_id filter is applied before/alongside similarity
    ranking. Similarity score is NEVER an authorization mechanism.

All methods take the CALLER's SQLAlchemy connection (or Session) rather than
opening their own — request paths run inside one transaction on one pooled
connection, which prevents nested pool checkouts from deadlocking a
size-1 pool and keeps delete/retry cleanup atomic with the caller's work.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy import text as sql_text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: uuid.UUID
    chunk_index: int
    page_start: int
    page_end: int
    section: str | None
    text: str
    score: float  # cosine similarity in [0, 1] for pgvector cosine distance


def _connection_of(conn_or_session: Connection | Session) -> Connection:
    if isinstance(conn_or_session, Session):
        return conn_or_session.connection()
    return conn_or_session


class VectorStore(ABC):
    @abstractmethod
    def replace_document_chunks(
        self,
        conn: Connection | Session,
        document_id: uuid.UUID,
        rows: list[dict],
        embeddings: list[list[float]],
    ) -> int:
        """Insert chunk rows with embeddings, replacing any previous chunks
        for the document inside the caller's transaction (retry idempotency)."""

    @abstractmethod
    def retrieve(
        self,
        conn: Connection | Session,
        document_id: uuid.UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Top-k chunks restricted to `document_id` — never a global search."""

    @abstractmethod
    def delete_document(self, conn: Connection | Session, document_id: uuid.UUID) -> int:
        """Delete all chunks/vectors of a document; returns rows removed."""


class PgVectorStore(VectorStore):
    def replace_document_chunks(
        self,
        conn: Connection | Session,
        document_id: uuid.UUID,
        rows: list[dict],
        embeddings: list[list[float]],
    ) -> int:
        if len(rows) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        connection = _connection_of(conn)
        connection.execute(
            sql_text("DELETE FROM document_chunks WHERE document_id = :doc"),
            {"doc": document_id},
        )
        for row, vector in zip(rows, embeddings):
            connection.execute(
                sql_text(
                    """
                    INSERT INTO document_chunks
                        (id, document_id, chunk_index, page_start, page_end,
                         section, text, token_count, embedding)
                    VALUES
                        (:id, :document_id, :chunk_index, :page_start, :page_end,
                         :section, :text, :token_count, CAST(:embedding AS vector))
                    """
                ),
                {
                    "id": row["id"],
                    "document_id": document_id,
                    "chunk_index": row["chunk_index"],
                    "page_start": row["page_start"],
                    "page_end": row["page_end"],
                    "section": row.get("section"),
                    "text": row["text"],
                    "token_count": row.get("token_count"),
                    "embedding": "[" + ",".join(repr(x) for x in vector) + "]",
                },
            )
        return len(rows)

    def retrieve(
        self,
        conn: Connection | Session,
        document_id: uuid.UUID,
        query_vector: list[float],
        top_k: int,
    ) -> list[RetrievedChunk]:
        connection = _connection_of(conn)
        query_vector_literal = "[" + ",".join(repr(x) for x in query_vector) + "]"
        result = connection.execute(
            sql_text(
                # document scope is part of the query itself — mandatory.
                # CAST() form used instead of `::` because SQLAlchemy's
                # text() bind-param regex does not convert `:param::type`.
                """
                SELECT id, chunk_index, page_start, page_end, section, text,
                       1 - (embedding <=> CAST(:qv AS vector)) AS score
                FROM document_chunks
                WHERE document_id = :doc
                ORDER BY embedding <=> CAST(:qv AS vector)
                LIMIT :k
                """
            ),
            {"doc": document_id, "qv": query_vector_literal, "k": top_k},
        )
        return [
            RetrievedChunk(
                chunk_id=row.id,
                chunk_index=row.chunk_index,
                page_start=row.page_start,
                page_end=row.page_end,
                section=row.section,
                text=row.text,
                score=float(row.score),
            )
            for row in result
        ]

    def delete_document(self, conn: Connection | Session, document_id: uuid.UUID) -> int:
        connection = _connection_of(conn)
        result = connection.execute(
            sql_text("DELETE FROM document_chunks WHERE document_id = :doc"),
            {"doc": document_id},
        )
        return result.rowcount or 0


class InMemoryVectorStore(VectorStore):
    """Test double ONLY — never wired into the production app (Phase 27)."""

    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, list[tuple[dict, list[float]]]] = {}

    def replace_document_chunks(self, conn, document_id, rows, embeddings) -> int:
        self._rows[document_id] = list(zip(rows, embeddings))
        return len(rows)

    def retrieve(self, conn, document_id, query_vector, top_k) -> list[RetrievedChunk]:
        stored = self._rows.get(document_id, [])
        scored = []
        for row, vector in stored:
            score = _cosine(query_vector, vector)
            scored.append(
                RetrievedChunk(
                    chunk_id=row["id"],
                    chunk_index=row["chunk_index"],
                    page_start=row["page_start"],
                    page_end=row["page_end"],
                    section=row.get("section"),
                    text=row["text"],
                    score=score,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:top_k]

    def delete_document(self, conn, document_id) -> int:
        return len(self._rows.pop(document_id, []))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return max(0.0, min(1.0, dot / (na * nb)))
