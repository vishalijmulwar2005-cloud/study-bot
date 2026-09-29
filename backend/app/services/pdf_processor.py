"""DocumentProcessor abstraction + PyMuPDF implementation (Phases 5–6).

Authoritative backend validation — the frontend check is never trusted:
extension, MIME type, PDF signature (%PDF-), size, page count, encryption,
and readability are all verified server-side with stable error codes.
"""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import fitz  # PyMuPDF

from app.core.errors import AppError, ErrorCode

PDF_MIME = "application/pdf"

# A page with fewer characters than this is considered image-only.
MIN_CHARS_PER_PAGE = 20
# If more than this fraction of pages look image-only, treat as scanned.
SCANNED_PAGE_FRACTION = 0.7

# --- Repeated header/footer stripping (retrieval text quality) -------------
# Word-processor exports repeat the document title / running head / page
# numbers on every page. Left in, that boilerplate prefixes every chunk and
# compresses all chunk embeddings together (they share most of their leading
# tokens), which suppresses real query-document similarity and undermines the
# evidence gate. Lines that repeat across nearly every page near the top or
# bottom edge are treated as page furniture and removed before chunking.
FURNITURE_MIN_PAGES = 3            # need repetition evidence across pages
FURNITURE_MIN_PAGE_FRACTION = 0.7  # must appear on >= 70% of pages
FURNITURE_EDGE_LINES = 3           # only first/last 3 non-empty lines
FURNITURE_MAX_CHARS = 120          # furniture lines are short


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-based, preserved through the whole pipeline
    text: str


class DocumentProcessor(ABC):
    @abstractmethod
    def validate(self, data: bytes, content_type: str | None, filename: str) -> None:
        """Raise AppError with a stable code when the upload is unacceptable."""

    @abstractmethod
    def extract_pages(self, data: bytes) -> list[PageText]:
        """Extract normalized per-page text; raises when OCR would be required."""


class DocumentValidationError(AppError):
    pass


def _invalid(message: str | None = None) -> DocumentValidationError:
    return DocumentValidationError(ErrorCode.INVALID_PDF, message)


class PyMuPdfProcessor(DocumentProcessor):
    def __init__(self, max_bytes: int, max_pages: int):
        self.max_bytes = max_bytes
        self.max_pages = max_pages

    def validate(self, data: bytes, content_type: str | None, filename: str) -> None:
        if not filename.lower().endswith(".pdf"):
            raise DocumentValidationError(ErrorCode.UNSUPPORTED_MEDIA)
        if content_type is not None and content_type not in (
            PDF_MIME,
            "application/octet-stream",  # some browsers send this for PDFs
            "",
        ):
            raise DocumentValidationError(ErrorCode.UNSUPPORTED_MEDIA)
        if len(data) == 0:
            raise _invalid("The uploaded file is empty.")
        if len(data) > self.max_bytes:
            raise DocumentValidationError(ErrorCode.FILE_TOO_LARGE)
        if not data[:5] == b"%PDF-":
            # Signature check: do not trust extension/MIME alone (Security §05).
            raise _invalid()
        try:
            with fitz.open(stream=data, filetype="pdf") as doc:
                if doc.needs_pass:
                    raise DocumentValidationError(
                        ErrorCode.INVALID_PDF,
                        "Password-protected PDFs are not supported. "
                        "Please upload an accessible copy.",
                    )
                if doc.page_count == 0:
                    raise _invalid("The PDF contains no pages.")
                if doc.page_count > self.max_pages:
                    raise DocumentValidationError(
                        ErrorCode.INVALID_PDF,
                        f"The PDF exceeds the maximum of {self.max_pages} pages.",
                    )
        except DocumentValidationError:
            raise
        except Exception as exc:  # corrupted/invalid structure
            raise _invalid() from exc

    def extract_pages(self, data: bytes) -> list[PageText]:
        try:
            with fitz.open(stream=data, filetype="pdf") as doc:
                if doc.needs_pass:
                    raise DocumentValidationError(ErrorCode.INVALID_PDF)
                pages: list[PageText] = []
                for index, page in enumerate(doc):
                    raw = page.get_text("text") or ""
                    text = _normalize(raw)
                    pages.append(PageText(page_number=index + 1, text=text))
        except DocumentValidationError:
            raise
        except Exception as exc:
            raise DocumentValidationError(ErrorCode.EXTRACTION_FAILED) from exc

        pages = _strip_repeated_furniture(pages)

        image_only = sum(1 for p in pages if len(p.text) < MIN_CHARS_PER_PAGE)
        if pages and image_only / len(pages) >= SCANNED_PAGE_FRACTION:
            # Documented failure path (App Flow 09): OCR unavailable -> fail safely.
            raise DocumentValidationError(ErrorCode.OCR_UNAVAILABLE)
        if not any(p.text.strip() for p in pages):
            raise DocumentValidationError(ErrorCode.EMPTY_DOCUMENT)
        return pages


def _furniture_key(line: str) -> str:
    """Counting key for a furniture line.

    Digit masking is deliberately narrow: it only applies to lines that are
    (almost) entirely a page number — 'Page 12', '12', '- 3 -', 'p. 12'.
    Masking digits everywhere would collapse genuinely different short body
    lines ('results: 3 items' vs 'results: 5 items') into apparent repeats.
    """
    stripped = line.strip()
    if re.fullmatch(r"\D{0,6}\d{1,4}\D{0,6}", stripped):
        return re.sub(r"\d+", "#", stripped)
    return stripped


def _strip_repeated_furniture(pages: list[PageText]) -> list[PageText]:
    """Remove header/footer lines repeated across (nearly) all pages.

    Only lines within the first/last FURNITURE_EDGE_LINES non-empty lines of
    a page are eligible, and only when the same text (digit-masked) appears
    on at least FURNITURE_MIN_PAGE_FRACTION of pages — real content is never
    repeated often enough to match. Short documents keep everything: there
    is no reliable repetition evidence.
    """
    if len(pages) < FURNITURE_MIN_PAGES:
        return pages

    required = max(2, math.ceil(FURNITURE_MIN_PAGE_FRACTION * len(pages)))
    counts: dict[str, int] = {}
    for page in pages:
        lines = [ln.strip() for ln in page.text.splitlines() if ln.strip()]
        edge = lines[:FURNITURE_EDGE_LINES] + lines[-FURNITURE_EDGE_LINES:]
        seen_on_page: set[str] = set()
        for line in edge:
            if len(line) <= FURNITURE_MAX_CHARS:
                seen_on_page.add(_furniture_key(line))
        for key in seen_on_page:
            counts[key] = counts.get(key, 0) + 1
    furniture_keys = {key for key, n in counts.items() if n >= required}
    if not furniture_keys:
        return pages

    stripped: list[PageText] = []
    for page in pages:
        lines = [ln.strip() for ln in page.text.splitlines()]
        nonempty = [i for i, ln in enumerate(lines) if ln]
        if not nonempty:
            stripped.append(page)
            continue
        first, last = nonempty[0], nonempty[-1]
        kept = [
            ln
            for i, ln in enumerate(lines)
            if not (
                ln
                and _furniture_key(ln) in furniture_keys
                and (i <= first + FURNITURE_EDGE_LINES - 1 or i >= last - FURNITURE_EDGE_LINES + 1)
            )
        ]
        text = "\n".join(kept).strip()
        # Safety: never let stripping empty out a page that had content.
        stripped.append(PageText(page.page_number, text if text else page.text))
    return stripped


def _normalize(text: str) -> str:
    """Collapse whitespace noise while keeping paragraph/heading boundaries."""
    lines = [line.strip() for line in text.splitlines()]
    cleaned: list[str] = []
    for line in lines:
        if line:
            cleaned.append(line)
        elif cleaned and cleaned[-1] != "":
            cleaned.append("")
    normalized = "\n".join(cleaned).strip()
    # Strip control characters that could confuse the prompt delimiters.
    return "".join(ch for ch in normalized if ch == "\n" or ord(ch) >= 32)
