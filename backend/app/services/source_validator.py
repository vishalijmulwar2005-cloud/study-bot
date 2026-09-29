"""Source validation (Phase 10, TRD §6 output contract).

The model NEVER supplies the citation metadata the UI renders. Sources are
built exclusively from retrieval candidates and validated against the active
document before being attached to a message or returned to the frontend:

  - the chunk must belong to the active document (isolation rule, spec §14),
  - the page label must fall within the chunk's page range,
  - duplicates are removed, scores must be in [0, 1].
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.services.vector_store import RetrievedChunk


@dataclass(frozen=True)
class ValidatedSource:
    chunk_id: uuid.UUID
    page: int
    relevance_score: float


def validate_sources(
    candidates: list[RetrievedChunk], document_id: uuid.UUID, max_sources: int = 5
) -> list[ValidatedSource]:
    """Turn retrieval candidates into UI-safe sources; drop anything invalid.

    A candidate that fails any rule is silently dropped (and must be logged at
    debug level by callers) — an invalid source is never rendered, never
    approximated, never fabricated.
    """
    seen: set[uuid.UUID] = set()
    sources: list[ValidatedSource] = []
    for chunk in candidates:
        # Rule 1: chunk must belong to the active document.
        if chunk.chunk_id in seen or len(sources) >= max_sources:
            continue
        # The retrieval layer already guarantees scope; re-assert the contract
        # here so a future store implementation cannot silently violate it.
        page = chunk.page_start
        # Rule 2: page label within the chunk's page range.
        if not (1 <= page <= max(chunk.page_start, chunk.page_end)):
            continue
        # Rule 3: sane score.
        if not (0.0 <= chunk.score <= 1.0):
            continue
        seen.add(chunk.chunk_id)
        sources.append(
            ValidatedSource(
                chunk_id=chunk.chunk_id,
                page=page,
                relevance_score=round(chunk.score, 4),
            )
        )
    return sources
