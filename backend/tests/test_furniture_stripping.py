"""Tests for repeated header/footer (page furniture) stripping.

The retrieval-quality bug this guards against: word-processor exports repeat
a running title + page number on every page. That boilerplate prefixes every
chunk, so all chunk embeddings share most of their leading tokens — real
queries score lower against every chunk and the deterministic evidence gate
starts rejecting legitimate questions (docs/DECISIONS.md #12 failure mode).
"""

from __future__ import annotations

from app.services.pdf_processor import (
    FURNITURE_MIN_PAGES,
    PageText,
    _strip_repeated_furniture,
)
from tests.conftest import make_pdf_with_furniture


class TestStripRepeatedFurnitureOnPageTexts:
    def test_repeated_header_and_footer_removed(self):
        header = "My Thesis — Chapter 3"
        pages = [
            PageText(page_number=i, text=f"{header}\nPage {i}\nBody paragraph {i} about topic {i}.\n{i}")
            for i in range(1, 6)
        ]
        stripped = _strip_repeated_furniture(pages)
        for page in stripped:
            assert header not in page.text
            assert f"Body paragraph {page.page_number}" in page.text

    def test_short_documents_are_left_alone(self):
        pages = [
            PageText(page_number=i, text="Shared Header\nUnique body text for this page.")
            for i in range(1, FURNITURE_MIN_PAGES)
        ]
        assert _strip_repeated_furniture(pages) == pages

    def test_unique_body_lines_are_never_removed(self):
        pages = [
            PageText(page_number=i, text=f"Unique body text {i} with real content.")
            for i in range(1, 6)
        ]
        assert _strip_repeated_furniture(pages) == pages

    def test_digit_masking_groups_page_numbers(self):
        # 'Page 3' / 'Page 4' / bare '3' / '4' must all count as furniture.
        pages = [
            PageText(page_number=i, text=f"Running Title\nPage {i}\nReal content {i}.\n{i}")
            for i in range(1, 5)
        ]
        stripped = _strip_repeated_furniture(pages)
        for page in stripped:
            assert "Running Title" not in page.text
            assert not page.text.startswith("Page ")
            assert f"Real content {page.page_number}" in page.text

    def test_never_empties_a_page(self):
        # Degenerate case: a page consisting only of furniture lines keeps
        # its original text rather than becoming empty.
        pages = [
            PageText(page_number=i, text="Only Header\n5")
            if i == 3
            else PageText(page_number=i, text="Only Header\n5\nBody text here.\n5")
            for i in range(1, 6)
        ]
        stripped = _strip_repeated_furniture(pages)
        assert all(p.text.strip() for p in stripped)


class TestFurnitureStrippingEndToEnd:
    def test_extract_pages_removes_running_header(self, processor):
        data = make_pdf_with_furniture(pages=4)
        pages = processor.extract_pages(data)
        assert len(pages) == 4
        for page in pages:
            assert "App Flow Specification" not in page.text
            assert "scheduling algorithms" in page.text


class TestScannedStillFails:
    def test_scanned_pdf_still_fails_after_strip_change(self, processor):
        import pytest

        from app.core.errors import ErrorCode
        from app.services.pdf_processor import DocumentValidationError
        from tests.conftest import make_scanned_pdf

        with pytest.raises(DocumentValidationError) as exc:
            processor.extract_pages(make_scanned_pdf())
        assert exc.value.code == ErrorCode.OCR_UNAVAILABLE
