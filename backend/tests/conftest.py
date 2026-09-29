"""Shared test fixtures and TEST-ONLY provider fakes.

These fakes exist exclusively for tests (Phase 27: no mock RAG in the
production path). The production bundle is built in app/bundle.py from
real environment configuration.
"""

from __future__ import annotations

import hashlib
import math
import re

import pytest

from app.core.rate_limit import RateLimiter
from app.services.chunker import Chunker, ChunkerConfig
from app.services.embeddings import EmbeddingService
from app.services.llm import LLMService
from app.services.pdf_processor import PyMuPdfProcessor
from app.services.vector_store import InMemoryVectorStore

TEST_DIM = 64
_TOKEN_RE = re.compile(r"[a-z0-9]+")


class HashBagEmbedding(EmbeddingService):
    """Deterministic bag-of-words embedding for tests.

    Tokens are hashed into a fixed-dim vector and L2-normalized, so texts
    sharing vocabulary get high cosine similarity and unrelated texts score
    near zero — enough to exercise the evidence gate deterministically.
    """

    def __init__(self, dim: int = TEST_DIM):
        self.dim = dim

    @property
    def configured(self) -> bool:
        return True

    def _vector_for(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for token in _TOKEN_RE.findall(text.lower()):
            index = int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dim
            vec[index] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._vector_for(t) for t in texts]


class CannedLLM(LLMService):
    """Returns a fixed grounded answer; records the last prompt it received."""

    def __init__(self, answer: str = "The proposed method introduces a new scheduling algorithm (page 1)."):
        self.answer = answer
        self.last_messages: list[dict[str, str]] | None = None

    @property
    def configured(self) -> bool:
        return True

    async def complete(self, messages: list[dict[str, str]], max_tokens: int) -> str:
        self.last_messages = messages
        return self.answer


@pytest.fixture
def fake_embedding() -> HashBagEmbedding:
    return HashBagEmbedding()


@pytest.fixture
def fake_llm() -> CannedLLM:
    return CannedLLM()


@pytest.fixture
def vector_store() -> InMemoryVectorStore:
    return InMemoryVectorStore()


@pytest.fixture
def chunker() -> Chunker:
    return Chunker(ChunkerConfig(target_tokens=60, overlap_tokens=10))


@pytest.fixture
def processor() -> PyMuPdfProcessor:
    return PyMuPdfProcessor(max_bytes=1024 * 1024, max_pages=50)


@pytest.fixture
def limiter():
    return RateLimiter(window_seconds=60)


def make_pdf(pages: int = 1, text: str | None = None, encrypted: bool = False) -> bytes:
    """Build a real (multi-page) PDF in memory using PyMuPDF."""
    import fitz

    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        body = (
            text
            if text is not None
            else f"Page {i + 1} discusses scheduling algorithms in operating systems."
        )
        page.insert_text((72, 72), body, fontsize=12)
    if encrypted:
        data = doc.tobytes(
            encryption=fitz.PDF_ENCRYPT_AES_256,
            owner_pw="secret",
            user_pw="secret",
        )
    else:
        data = doc.tobytes()
    doc.close()
    return data


def make_scanned_pdf() -> bytes:
    """A PDF whose pages contain only an image (no extractable text)."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    # A tiny blank pixmap rendered into the page = image-only page.
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 10, 10))
    page.insert_image(fitz.Rect(10, 10, 190, 190), pixmap=pix)
    data = doc.tobytes()
    doc.close()
    return data


def make_pdf_with_furniture(pages: int = 4, body: str | None = None) -> bytes:
    """A PDF that mimics word-processor exports: a running title header,
    a page-number footer, and page body text."""
    import fitz

    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 40), "PDF & Notes Q&A Chatbot — App Flow Specification", fontsize=10)
        page.insert_text((72, 56), f"Page {i + 1}", fontsize=10)
        text = (
            body
            if body is not None
            else f"Section {i + 1} explains scheduling algorithms in operating systems."
        )
        page.insert_text((72, 120), text, fontsize=12)
        page.insert_text((72, 760), "12", fontsize=10)  # bare page number footer
    data = doc.tobytes()
    doc.close()
    return data
