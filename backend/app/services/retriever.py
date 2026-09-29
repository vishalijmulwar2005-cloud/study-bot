"""Retriever + deterministic evidence gate (Phases 7–8, TRD §5, Security §06).

Pipeline per question:
    question -> query embedding -> document-scoped vector search -> candidates
             -> evidence gate (threshold on top-1 similarity) -> decision

The gate is deterministic: no LLM self-assessment. When evidence is
insufficient the LLM is never called and the product's no-evidence response
is returned (grounded=false, sources=[]).
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.logging import get_logger, log_event
from app.services.embeddings import EmbeddingService
from app.services.vector_store import RetrievedChunk, VectorStore

logger = get_logger("app.retrieval")

# Product trust control (Security §06): the exact no-evidence response. An
# optional UI suggestion line is rendered by the frontend, not stored here.
NO_EVIDENCE_ANSWER = "I couldn't find this information in the uploaded PDF."


class Retriever(ABC):
    @abstractmethod
    async def retrieve(
        self,
        conn,
        document_id: uuid.UUID,
        question: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        """Embed the question and return document-scoped candidate chunks.

        `conn` is the caller's SQLAlchemy Connection/Session — vector queries
        run on the caller's transaction (see vector_store.py)."""


class EmbeddingRetriever(Retriever):
    def __init__(self, embeddings: EmbeddingService, store: VectorStore):
        self.embeddings = embeddings
        self.store = store

    async def retrieve(
        self,
        conn,
        document_id: uuid.UUID,
        question: str,
        top_k: int,
    ) -> list[RetrievedChunk]:
        [query_vector] = await self.embeddings.embed_texts([question])
        # VectorStore.retrieve itself enforces the document scope; this call
        # site is the second enforcement point (defense in depth).
        return self.store.retrieve(conn, document_id, query_vector, top_k)


@dataclass(frozen=True)
class EvidenceDecision:
    sufficient: bool
    top_score: float
    candidate_count: int
    reason: str


def evaluate_evidence(
    candidates: list[RetrievedChunk], threshold: float, min_chars: int = 40
) -> EvidenceDecision:
    """Deterministic evidence gate (docs/DECISIONS.md #12).

    Evidence is sufficient only when:
      - at least one candidate chunk was retrieved from the active document, and
      - the best candidate's cosine similarity >= threshold, and
      - the best candidate actually carries usable text.
    """
    if not candidates:
        return EvidenceDecision(False, 0.0, 0, "no candidates retrieved")
    best = candidates[0]
    if best.score < threshold:
        return EvidenceDecision(
            False, best.score, len(candidates), "top score below threshold"
        )
    if len(best.text.strip()) < min_chars:
        return EvidenceDecision(
            False, best.score, len(candidates), "top candidate text too short"
        )
    return EvidenceDecision(True, best.score, len(candidates), "evidence sufficient")


def log_retrieval_event(
    logger_name: str,
    document_id: uuid.UUID,
    decision: EvidenceDecision,
    top_k: int,
    reformulated: bool = False,
) -> None:
    """Log retrieval metadata only — never question or chunk text."""
    log_event(
        get_logger(logger_name),
        "retrieval decision",
        document_id=str(document_id),
        sufficient=decision.sufficient,
        top_score=round(decision.top_score, 4),
        candidates=decision.candidate_count,
        top_k=top_k,
        reformulated=reformulated or None,
    )
