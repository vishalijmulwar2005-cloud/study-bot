"""Evidence gate + source validation + retrieval scoping tests (Phases 7–8, 10)."""

from __future__ import annotations

import uuid

from app.services.retriever import evaluate_evidence
from app.services.source_validator import validate_sources
from app.services.vector_store import InMemoryVectorStore, RetrievedChunk

DOC = uuid.uuid4()


def chunk(score: float, text: str = "Deadlock requires mutual exclusion and hold and wait.", page=4) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        chunk_index=0,
        page_start=page,
        page_end=page,
        section=None,
        text=text,
        score=score,
    )


class TestEvidenceGate:
    def test_sufficient_when_top_score_above_threshold(self):
        decision = evaluate_evidence([chunk(0.81)], threshold=0.25)
        assert decision.sufficient is True

    def test_insufficient_when_below_threshold(self):
        decision = evaluate_evidence([chunk(0.1)], threshold=0.25)
        assert decision.sufficient is False
        assert "below threshold" in decision.reason

    def test_insufficient_when_no_candidates(self):
        decision = evaluate_evidence([], threshold=0.25)
        assert decision.sufficient is False
        assert decision.candidate_count == 0

    def test_insufficient_when_top_candidate_is_empty_text(self):
        decision = evaluate_evidence([chunk(0.9, text="  ")], threshold=0.25)
        assert decision.sufficient is False

    def test_gate_is_deterministic(self):
        candidates = [chunk(0.3), chunk(0.2)]
        outcomes = {evaluate_evidence(candidates, 0.25).sufficient for _ in range(5)}
        assert outcomes == {True}


class TestInMemoryStoreScoping:
    """The store must only ever return the requested document's chunks."""

    def test_retrieve_never_crosses_documents(self):
        store = InMemoryVectorStore()
        doc_a, doc_b = uuid.uuid4(), uuid.uuid4()

        def row(index: int) -> dict:
            return {
                "id": uuid.uuid4(),
                "chunk_index": index,
                "page_start": 1,
                "page_end": 1,
                "section": None,
                "text": f"chunk {index}",
                "token_count": 10,
            }

        va = [1.0, 0.0, 0.0]
        vb = [0.0, 1.0, 0.0]
        store.replace_document_chunks(None, doc_a, [row(0)], [va])
        store.replace_document_chunks(None, doc_b, [row(0)], [vb])

        # Query identical to A's vector, but scoped to B: only B's chunk.
        results_b = store.retrieve(None, doc_b, va, top_k=5)
        assert len(results_b) == 1
        results_a = store.retrieve(None, doc_a, va, top_k=5)
        assert len(results_a) == 1

        # After deleting A, nothing retrievable remains (delete verification).
        assert store.delete_document(None, doc_a) == 1
        assert store.retrieve(None, doc_a, va, top_k=5) == []

    def test_top_k_limits_results(self):
        store = InMemoryVectorStore()
        rows = [
            {
                "id": uuid.uuid4(),
                "chunk_index": i,
                "page_start": i + 1,
                "page_end": i + 1,
                "section": None,
                "text": f"chunk {i}",
                "token_count": 10,
            }
            for i in range(6)
        ]
        vecs = [[float(i), 1.0, 0.0] for i in range(6)]
        store.replace_document_chunks(None, DOC, rows, vecs)
        assert len(store.retrieve(None, DOC, [0.0, 1.0, 0.0], top_k=3)) == 3


class TestSourceValidation:
    def test_sources_capped_and_deduplicated(self):
        target = chunk(0.9)
        duplicates = [
            RetrievedChunk(
                chunk_id=target.chunk_id,
                chunk_index=0,
                page_start=4,
                page_end=4,
                section=None,
                text="same",
                score=0.85,
            )
        ]
        sources = validate_sources([target, *duplicates, chunk(0.8)], DOC, max_sources=2)
        assert len(sources) == 2
        assert len({s.chunk_id for s in sources}) == 2

    def test_page_label_within_chunk_range(self):
        c = chunk(0.9, page=7)
        c = RetrievedChunk(
            chunk_id=c.chunk_id,
            chunk_index=0,
            page_start=7,
            page_end=9,
            section=None,
            text=c.text,
            score=0.9,
        )
        [source] = validate_sources([c], DOC)
        assert 7 <= source.page <= 9

    def test_invalid_score_dropped(self):
        c = chunk(1.5)  # impossible cosine
        assert validate_sources([c], DOC) == []

    def test_sources_carry_page_metadata_for_ui_chips(self):
        [source] = validate_sources([chunk(0.87)], DOC)
        assert source.page == 4
        assert 0.0 <= source.relevance_score <= 1.0
