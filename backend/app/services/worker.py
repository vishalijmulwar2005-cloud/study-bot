"""Background processing worker (Phase 6).

MVP queue: DB-backed processing_jobs claimed by a polling asyncio worker
inside the API process (docs/DECISIONS.md #6). Claims use UPDATE ... WHERE
status='QUEUED' ... FOR UPDATE SKIP LOCKED so a job is claimed exactly once.

Pipeline per job:
    EXTRACT -> CHUNK -> EMBED -> INDEX -> document READY

Failure contract:
    - job + document marked FAILED with a SAFE error code (never exception text),
    - retry re-queues the job; chunk replacement is transactional and
      idempotent (replace_document_chunks clears previous chunks first),
    - a document never becomes READY from a failed pipeline,
    - deletion while processing cancels the job without resurrecting the doc.

Logging is privacy-minimized: counts, stages, durations, IDs — never text.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from sqlalchemy import text as sql_text

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger, log_event
from app.models import DocumentStatus, JobStage, can_transition
from app.services.chunker import Chunker
from app.services.embeddings import EmbeddingService
from app.services.pdf_processor import DocumentProcessor
from app.services.storage import StorageError, StorageService
from app.services.vector_store import VectorStore

logger = get_logger("app.worker")

POLL_INTERVAL_SECONDS = 1.0
ERROR_BACKOFF_SECONDS = 5.0


@dataclass
class WorkerComponents:
    storage: StorageService
    processor: DocumentProcessor
    chunker: Chunker
    embeddings: EmbeddingService
    store: VectorStore


class ProcessingWorker:
    def __init__(self, components: WorkerComponents):
        self.components = components
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    # ---------- lifecycle ----------

    def start(self) -> None:
        if self._task is None:
            self._stopping.clear()
            self._task = asyncio.create_task(self._run(), name="processing-worker")
            log_event(logger, "worker started")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 — shutdown must not raise
                pass
            self._task = None
            log_event(logger, "worker stopped")

    def requeue_stale_running_jobs(self) -> None:
        """Single-process MVP: on startup, any RUNNING job is a leftover from
        a previous process. Requeue it (the pipeline is idempotent).

        Failure to reach the database must never block application startup —
        the worker loop retries on every tick anyway."""
        from app.database import get_engine

        try:
            with get_engine().begin() as conn:
                conn.execute(
                    sql_text(
                        """
                        UPDATE processing_jobs
                        SET status = 'QUEUED', stage = 'QUEUED', started_at = NULL
                        WHERE status = 'RUNNING'
                        """
                    )
                )
            log_event(logger, "stale running jobs requeued")
        except Exception as exc:  # noqa: BLE001 — startup must not depend on the DB
            log_event(
                logger,
                "could not requeue stale jobs (database unreachable)",
                level=30,
                detail=exc.__class__.__name__,
            )

    # ---------- loop ----------

    async def _run(self) -> None:
        from app.database import get_engine

        while not self._stopping.is_set():
            try:
                claimed = await asyncio.to_thread(self._claim_next, get_engine())
                if claimed is not None:
                    job_id, document_id = claimed
                    await self._process_job(job_id, document_id)
                    continue  # drain the queue before sleeping
                await self._sleep(POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — the worker must survive anything
                log_event(logger, "worker tick failed", level=40, detail=exc.__class__.__name__)
                await self._sleep(ERROR_BACKOFF_SECONDS)

    async def _sleep(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stopping.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    def _claim_next(self, engine) -> tuple[uuid.UUID, uuid.UUID] | None:
        with engine.begin() as conn:
            row = conn.execute(
                sql_text(
                    """
                    UPDATE processing_jobs
                    SET status = 'RUNNING', started_at = now(), stage = 'EXTRACT'
                    WHERE id = (
                        SELECT id FROM processing_jobs
                        WHERE status = 'QUEUED'
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    RETURNING id, document_id
                    """
                )
            ).fetchone()
        if row is None:
            return None
        return row.id, row.document_id

    # ---------- pipeline ----------

    async def _process_job(self, job_id: uuid.UUID, document_id: uuid.UUID) -> None:
        from app.database import get_engine

        engine = get_engine()
        started = time.monotonic()
        stage = JobStage.EXTRACT
        try:
            current = await asyncio.to_thread(self._document_status, engine, document_id)
            if current is None:
                await asyncio.to_thread(self._fail_job, engine, job_id, ErrorCode.NOT_FOUND)
                return
            if current in (DocumentStatus.DELETING, DocumentStatus.DELETED):
                # Document deleted mid-queue: never process it.
                await asyncio.to_thread(self._fail_job, engine, job_id, "DOCUMENT_CANCELLED")
                log_event(logger, "job cancelled (document deleted)", job_id=str(job_id))
                return
            if not can_transition(current, DocumentStatus.PROCESSING):
                await asyncio.to_thread(self._fail_job, engine, job_id, ErrorCode.INTERNAL_ERROR)
                return

            storage_key = await asyncio.to_thread(self._load_storage_key, engine, document_id)

            stage = JobStage.EXTRACT
            await asyncio.to_thread(self._set_stage, engine, job_id, JobStage.EXTRACT)
            data = await asyncio.to_thread(self.components.storage.load, storage_key)
            pages = await asyncio.to_thread(self.components.processor.extract_pages, data)

            stage = JobStage.CHUNK
            await asyncio.to_thread(self._set_stage, engine, job_id, JobStage.CHUNK)
            chunks = await asyncio.to_thread(self.components.chunker.chunk_pages, pages)
            if not chunks:
                raise AppError(ErrorCode.EMPTY_DOCUMENT)

            stage = JobStage.EMBED
            await asyncio.to_thread(self._set_stage, engine, job_id, JobStage.EMBED)
            embeddings = await self.components.embeddings.embed_texts([c.text for c in chunks])

            stage = JobStage.INDEX
            await asyncio.to_thread(self._set_stage, engine, job_id, JobStage.INDEX)
            rows = [
                {
                    "id": uuid.uuid4(),
                    "chunk_index": chunk.chunk_index,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "section": chunk.section,
                    "text": chunk.text,
                    "token_count": chunk.token_count,
                }
                for chunk in chunks
            ]

            def _index_and_finish() -> int:
                # Chunk replacement + READY in ONE transaction: a crash can
                # never leave indexed chunks without a READY document.
                with engine.begin() as conn:
                    inserted = self.components.store.replace_document_chunks(
                        conn, document_id, rows, embeddings
                    )
                    if inserted == 0:
                        raise AppError(ErrorCode.EMPTY_DOCUMENT)
                    self._succeed_in_conn(conn, job_id, document_id, len(pages))
                    return inserted

            inserted = await asyncio.to_thread(_index_and_finish)

            log_event(
                logger,
                "processing succeeded",
                job_id=str(job_id),
                document_id=str(document_id),
                pages=len(pages),
                chunks=inserted,
                seconds=round(time.monotonic() - started, 2),
            )
        except AppError as exc:
            # Safe, stable error code; exception details never reach the client.
            await asyncio.to_thread(
                self._fail_document_and_job, engine, job_id, document_id, exc.code
            )
            log_event(
                logger,
                "processing failed",
                level=40,
                job_id=str(job_id),
                document_id=str(document_id),
                stage=stage.value,
                error_code=exc.code,
                seconds=round(time.monotonic() - started, 2),
            )
        except StorageError:
            # B-4: storage outage must be distinguishable from a bad PDF.
            await asyncio.to_thread(
                self._fail_document_and_job,
                engine,
                job_id,
                document_id,
                ErrorCode.STORAGE_UNAVAILABLE,
            )
            log_event(
                logger,
                "processing failed",
                level=40,
                job_id=str(job_id),
                stage=stage.value,
                error_code=ErrorCode.STORAGE_UNAVAILABLE,
            )
        except Exception as exc:  # noqa: BLE001 — map everything to a safe code
            await asyncio.to_thread(
                self._fail_document_and_job,
                engine,
                job_id,
                document_id,
                ErrorCode.INTERNAL_ERROR,
            )
            log_event(
                logger,
                "processing failed",
                level=40,
                job_id=str(job_id),
                stage=stage.value,
                error_code=ErrorCode.INTERNAL_ERROR,
                detail=exc.__class__.__name__,
            )

    # ---------- DB helpers (sync; called via to_thread) ----------

    @staticmethod
    def _document_status(engine, document_id: uuid.UUID) -> DocumentStatus | None:
        with engine.connect() as conn:
            row = conn.execute(
                sql_text("SELECT status FROM documents WHERE id = :id"),
                {"id": document_id},
            ).fetchone()
        return DocumentStatus(row.status) if row is not None else None

    @staticmethod
    def _load_storage_key(engine, document_id: uuid.UUID) -> str:
        with engine.connect() as conn:
            row = conn.execute(
                sql_text("SELECT storage_key FROM documents WHERE id = :id"),
                {"id": document_id},
            ).fetchone()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return row.storage_key

    @staticmethod
    def _set_stage(engine, job_id: uuid.UUID, stage: JobStage) -> None:
        with engine.begin() as conn:
            conn.execute(
                sql_text("UPDATE processing_jobs SET stage = :s WHERE id = :id"),
                {"s": stage.value, "id": job_id},
            )

    @staticmethod
    def _succeed_in_conn(conn, job_id: uuid.UUID, document_id: uuid.UUID, page_count: int) -> None:
        conn.execute(
            sql_text(
                """
                UPDATE documents
                SET status = 'READY', error_code = NULL, page_count = :pages,
                    updated_at = now()
                WHERE id = :id AND status NOT IN ('DELETING', 'DELETED')
                """
            ),
            {"pages": page_count, "id": document_id},
        )
        conn.execute(
            sql_text(
                """
                UPDATE processing_jobs
                SET status = 'SUCCEEDED', stage = 'DONE', finished_at = now(),
                    error_code = NULL
                WHERE id = :id
                """
            ),
            {"id": job_id},
        )

    @classmethod
    def _fail_document_and_job(
        cls, engine, job_id: uuid.UUID, document_id: uuid.UUID, error_code: str
    ) -> None:
        try:
            with engine.begin() as conn:
                conn.execute(
                    sql_text(
                        """
                        UPDATE documents
                        SET status = 'FAILED', error_code = :code, updated_at = now()
                        WHERE id = :id AND status NOT IN ('DELETING', 'DELETED')
                        """
                    ),
                    {"code": error_code, "id": document_id},
                )
                cls._fail_job_in_conn(conn, job_id, error_code)
        except Exception:  # noqa: BLE001 — failing to record failure must not crash the worker
            log_event(logger, "failed to record job failure", level=40, job_id=str(job_id))

    @staticmethod
    def _fail_job(engine, job_id: uuid.UUID, error_code: str) -> None:
        with engine.begin() as conn:
            ProcessingWorker._fail_job_in_conn(conn, job_id, error_code)

    @staticmethod
    def _fail_job_in_conn(conn, job_id: uuid.UUID, error_code: str) -> None:
        conn.execute(
            sql_text(
                """
                UPDATE processing_jobs
                SET status = 'FAILED', finished_at = now(), error_code = :code
                WHERE id = :id
                """
            ),
            {"code": error_code, "id": job_id},
        )
