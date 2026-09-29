"""Upload validation tests (Phase 5 acceptance criteria)."""

from __future__ import annotations

import pytest

from app.core.errors import ErrorCode
from app.services.pdf_processor import DocumentValidationError
from tests.conftest import make_pdf, make_scanned_pdf


class TestUploadValidation:
    def test_valid_pdf_passes(self, processor):
        data = make_pdf(pages=2)
        processor.validate(data, "application/pdf", "lecture-notes.pdf")

    def test_wrong_extension_rejected_415(self, processor):
        data = make_pdf()
        with pytest.raises(DocumentValidationError) as exc:
            processor.validate(data, "application/pdf", "notes.txt")
        assert exc.value.code == ErrorCode.UNSUPPORTED_MEDIA
        assert exc.value.http_status == 415

    def test_wrong_mime_rejected_415(self, processor):
        data = make_pdf()
        with pytest.raises(DocumentValidationError) as exc:
            processor.validate(data, "image/png", "notes.pdf")
        assert exc.value.code == ErrorCode.UNSUPPORTED_MEDIA

    def test_renamed_executable_rejected_by_signature(self, processor):
        # A PNG renamed to .pdf must fail the %PDF- signature check.
        png = b"\x89PNG\r\n\x1a\n" + b"0" * 128
        with pytest.raises(DocumentValidationError) as exc:
            processor.validate(png, "application/pdf", "fake.pdf")
        assert exc.value.code == ErrorCode.INVALID_PDF
        assert exc.value.http_status == 422

    def test_empty_file_rejected(self, processor):
        with pytest.raises(DocumentValidationError) as exc:
            processor.validate(b"", "application/pdf", "empty.pdf")
        assert exc.value.code == ErrorCode.INVALID_PDF

    def test_oversized_file_rejected_413(self):
        from app.services.pdf_processor import PyMuPdfProcessor

        tiny = PyMuPdfProcessor(max_bytes=16, max_pages=50)
        data = make_pdf()
        with pytest.raises(DocumentValidationError) as exc:
            tiny.validate(data, "application/pdf", "big.pdf")
        assert exc.value.code == ErrorCode.FILE_TOO_LARGE
        assert exc.value.http_status == 413

    def test_page_limit_rejected_422(self):
        from app.services.pdf_processor import PyMuPdfProcessor

        one_page_limit = PyMuPdfProcessor(max_bytes=1024 * 1024, max_pages=1)
        data = make_pdf(pages=3)
        with pytest.raises(DocumentValidationError) as exc:
            one_page_limit.validate(data, "application/pdf", "long.pdf")
        assert exc.value.code == ErrorCode.INVALID_PDF

    def test_encrypted_pdf_rejected(self, processor):
        data = make_pdf(encrypted=True)
        with pytest.raises(DocumentValidationError) as exc:
            processor.validate(data, "application/pdf", "locked.pdf")
        assert exc.value.code == ErrorCode.INVALID_PDF

    def test_garbage_bytes_rejected(self, processor):
        with pytest.raises(DocumentValidationError) as exc:
            processor.validate(b"%PDF-1.7 not really a pdf \xff\xfe", "application/pdf", "bad.pdf")
        assert exc.value.code == ErrorCode.INVALID_PDF

    def test_scanned_pdf_fails_with_ocr_unavailable(self, processor):
        data = make_scanned_pdf()
        with pytest.raises(DocumentValidationError) as exc:
            processor.extract_pages(data)
        assert exc.value.code == ErrorCode.OCR_UNAVAILABLE

    def test_extraction_preserves_page_numbers(self, processor):
        data = make_pdf(pages=3)
        pages = processor.extract_pages(data)
        assert [p.page_number for p in pages] == [1, 2, 3]
        assert all("scheduling" in p.text for p in pages)
