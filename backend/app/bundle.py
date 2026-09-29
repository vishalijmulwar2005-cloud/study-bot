"""Service bundle: wires concrete provider implementations to interfaces.

Built once at startup from Settings; tests build a bundle with fake
providers. Production never uses test fakes (Phase 27).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.core.rate_limit import RateLimiter
from app.services.chunker import Chunker, ChunkerConfig
from app.services.embeddings import EmbeddingService, OpenAICompatibleEmbedding
from app.services.llm import LLMService, OpenAICompatibleLLM
from app.services.pdf_processor import DocumentProcessor, PyMuPdfProcessor
from app.services.retriever import EmbeddingRetriever, Retriever
from app.services.storage import LocalFileStorage, StorageService
from app.services.vector_store import PgVectorStore, VectorStore
from app.services.worker import WorkerComponents


@dataclass
class ServiceBundle:
    settings: Settings
    storage: StorageService
    processor: DocumentProcessor
    chunker: Chunker
    embeddings: EmbeddingService
    llm: LLMService
    store: VectorStore
    retriever: Retriever
    limiter: RateLimiter

    @property
    def worker_components(self) -> WorkerComponents:
        return WorkerComponents(
            storage=self.storage,
            processor=self.processor,
            chunker=self.chunker,
            embeddings=self.embeddings,
            store=self.store,
        )


def build_bundle(settings: Settings) -> ServiceBundle:
    storage = LocalFileStorage(Path(settings.storage_dir))
    processor = PyMuPdfProcessor(
        max_bytes=settings.max_upload_bytes, max_pages=settings.max_pdf_pages
    )
    chunker = Chunker(
        ChunkerConfig(
            target_tokens=settings.chunk_target_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
    )
    embeddings = OpenAICompatibleEmbedding(
        api_key=settings.embedding_api_key,
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        dim=settings.embedding_dim,
        batch_size=settings.embedding_batch_size,
        request_dimensions=settings.embedding_dimensions,
    )
    llm = OpenAICompatibleLLM(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    store: VectorStore = PgVectorStore()
    retriever = EmbeddingRetriever(embeddings, store)
    limiter = RateLimiter(window_seconds=settings.rate_limit_window_seconds)
    return ServiceBundle(
        settings=settings,
        storage=storage,
        processor=processor,
        chunker=chunker,
        embeddings=embeddings,
        llm=llm,
        store=store,
        retriever=retriever,
        limiter=limiter,
    )
