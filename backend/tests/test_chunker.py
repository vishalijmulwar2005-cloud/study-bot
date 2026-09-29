"""Chunker tests (Phase 6: page metadata must never be lost)."""

from __future__ import annotations

from app.services.chunker import Chunker, ChunkerConfig
from app.services.pdf_processor import PageText


def pages(*texts: str) -> list[PageText]:
    return [PageText(page_number=i + 1, text=t) for i, t in enumerate(texts)]


class TestChunker:
    def test_chunks_are_contiguous_and_unique_indexed(self, chunker):
        long_page = "\n\n".join(
            f"Paragraph {i} about deadlock prevention in operating systems with "
            "additional explanation text to grow the paragraph length further."
            for i in range(12)
        )
        chunks = chunker.chunk_pages(pages(long_page))
        assert len(chunks) > 1
        assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
        # All text must be covered by the chunks (no content dropped).
        joined = "\n\n".join(c.text for c in chunks)
        assert "Paragraph 0" in joined and "Paragraph 11" in joined

    def test_page_numbers_preserved(self):
        chunker = Chunker(ChunkerConfig(target_tokens=50, overlap_tokens=0))
        p1 = "Alpha page content. " * 10
        p2 = "Beta page content. " * 10
        p3 = "Gamma page content. " * 10
        chunks = chunker.chunk_pages(pages(p1, p2, p3))
        assert chunks, "expected chunks"
        assert chunks[0].page_start == 1
        assert chunks[-1].page_end == 3
        # Page range validity: start <= end for every chunk.
        for chunk in chunks:
            assert 1 <= chunk.page_start <= chunk.page_end <= 3

    def test_page_span_can_cross_boundary(self):
        chunker = Chunker(ChunkerConfig(target_tokens=500, overlap_tokens=0))
        joined = "Shared topic continues here. " * 30  # spans pages
        chunks = chunker.chunk_pages(pages(joined[:1200], joined[1200:]))
        assert any(c.page_start != c.page_end for c in chunks) or len(chunks) == 1

    def test_overlap_keeps_tail_content(self):
        chunker = Chunker(ChunkerConfig(target_tokens=40, overlap_tokens=15))
        text = "\n\n".join(f"Sentence number {i} about deadlocks." for i in range(10))
        chunks = chunker.chunk_pages(pages(text))
        assert len(chunks) >= 2
        first_words = set(chunks[0].text.split())
        second_words = set(chunks[1].text.split())
        assert first_words & second_words, "overlap should carry content across chunks"

    def test_section_heading_captured(self):
        chunker = Chunker(ChunkerConfig(target_tokens=50, overlap_tokens=0))
        text = "Chapter 3 Deadlocks\n\nDeadlock occurs when processes wait forever. " * 3
        chunks = chunker.chunk_pages(pages(text))
        assert chunks[0].section is not None
        assert "Chapter 3" in chunks[0].section

    def test_empty_document_yields_no_chunks(self, chunker):
        assert chunker.chunk_pages(pages("", "")) == []
