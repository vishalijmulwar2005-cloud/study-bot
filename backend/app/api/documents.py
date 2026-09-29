"""Document endpoints (Phase 5, 22, 4; API contract §09–§10).

POST   /api/v1/documents          upload + authoritative validation
GET    /api/v1/documents/{id}     metadata + status
GET    /api/v1/documents/{id}/status   processing status
POST   /api/v1/documents/{id}/retry    FAILED -> re-queue (documented addition)
DELETE /api/v1/documents/{id}     deletion workflow (idempotent)
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import select, text as sql_text
from sqlalchemy.orm import Session

from app.api.deps import get_bundle, get_db_session, get_identity, rate_limit
from app.bundle import ServiceBundle
from app.core.errors import AppError, ErrorCode
from app.core.filenames import sanitize_filename
from app.core.logging import get_logger, log_event
from app.core.security import Identity, ensure_owner_or_404
from app.database import Document, ProcessingJob
from app.models import DocumentStatus, JobStatus
from app.schemas import (
    DeleteResponse,
    DocumentResponse,
    DocumentStatusResponse,
    UploadResponse,
)
from app.services.storage import StorageError

router = APIRouter(prefix="/api/v1/documents", tags=["documents"])
logger = get_logger("app.api.documents")

_ALLOWED_STATUSES_FOR_RETRY = {DocumentStatus.FAILED}


def _load_owned_document(db: Session, document_id: uuid.UUID, identity: Identity) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.status == DocumentStatus.DELETED:
        raise AppError(ErrorCode.NOT_FOUND)
    ensure_owner_or_404(identity, document.session_id, "document")
    return document


@router.post(
    "",
    response_model=UploadResponse,
    status_code=201,
    dependencies=[Depends(rate_limit("upload", "rate_limit_upload_per_min"))],
)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db_session),
    bundle: ServiceBundle = Depends(get_bundle),
    identity: Identity = Depends(get_identity),
) -> UploadResponse:
    # Read with the configured cap enforced server-side (never trust the client).
    # Read at most cap+1 bytes so an oversized upload cannot exhaust memory
    # before the 413 is raised.
    limit = bundle.settings.max_upload_bytes
    data = await file.read(limit + 1)
    filename = file.filename or "upload.pdf"

    bundle.processor.validate(data, file.content_type, filename)

    try:
        storage_key = bundle.storage.save(data)
    except StorageError:
        # Storage outage is a dependency failure, not a PDF problem (B-4).
        raise AppError(ErrorCode.STORAGE_UNAVAILABLE)

    # B-1: display name is sanitized; storage key is server-generated, so
    # filesystem safety never depends on the filename.
    safe_name = sanitize_filename(filename)

    document = Document(
        filename=safe_name[:512],
        mime_type=file.content_type or "application/pdf",
        size_bytes=len(data),
        storage_key=storage_key,
        session_id=identity.token_hash,
    )
    db.add(document)
    db.flush()
    job = ProcessingJob(document_id=document.id)
    db.add(job)
    db.commit()

    log_event(
        logger,
        "upload accepted",
        document_id=str(document.id),
        job_id=str(job.id),
        size_bytes=len(data),
        pages=bundle.settings.max_pdf_pages,
    )
    return UploadResponse(
        document_id=document.id,
        # The worker claims the job within ~1s; report the truthful state.
        status=document.status.value,
        filename=document.filename,
        processing_job_id=job.id,
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db_session),
    identity: Identity = Depends(get_identity),
) -> DocumentResponse:
    document = _load_owned_document(db, document_id, identity)
    return DocumentResponse(
        document_id=document.id,
        filename=document.filename,
        status=document.status.value,
        page_count=document.page_count,
        error_code=document.error_code,
        created_at=document.created_at.isoformat(),
    )


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
def get_document_status(
    document_id: uuid.UUID,
    db: Session = Depends(get_db_session),
    bundle: ServiceBundle = Depends(get_bundle),
    identity: Identity = Depends(get_identity),
) -> DocumentStatusResponse:
    document = _load_owned_document(db, document_id, identity)
    stage: str | None = None
    if document.status in (DocumentStatus.UPLOADED, DocumentStatus.PROCESSING):
        job = db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.document_id == document.id)
            .order_by(ProcessingJob.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if job is not None and job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            stage = job.stage.value
    return DocumentStatusResponse(
        document_id=document.id,
        status=document.status.value,
        stage=stage,
        page_count=document.page_count,
        error_code=document.error_code,
    )


@router.post("/{document_id}/retry", response_model=DocumentStatusResponse)
def retry_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db_session),
    identity: Identity = Depends(get_identity),
) -> DocumentStatusResponse:
    document = _load_owned_document(db, document_id, identity)
    if document.status not in _ALLOWED_STATUSES_FOR_RETRY:
        raise AppError(
            ErrorCode.INVALID_REQUEST, "Only failed documents can be retried."
        )
    active_job = db.execute(
        select(ProcessingJob).where(
            ProcessingJob.document_id == document.id,
            ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
    ).scalar_one_or_none()
    if active_job is not None:
        raise AppError(ErrorCode.INVALID_REQUEST, "A processing job is already active.")

    job = ProcessingJob(document_id=document.id)
    db.add(job)
    db.commit()
    log_event(logger, "retry queued", document_id=str(document.id), job_id=str(job.id))
    return DocumentStatusResponse(
        document_id=document.id,
        status=document.status.value,
        stage=job.stage.value,
        page_count=document.page_count,
        error_code=document.error_code,
    )


@router.delete("/{document_id}", response_model=DeleteResponse)
def delete_document(
    document_id: uuid.UUID,
    db: Session = Depends(get_db_session),
    bundle: ServiceBundle = Depends(get_bundle),
    identity: Identity = Depends(get_identity),
) -> DeleteResponse:
    document = db.get(Document, document_id)

    # Idempotent: deleting a DELETED document reports success.
    if document is not None:
        ensure_owner_or_404(identity, document.session_id, "document")
        if document.status != DocumentStatus.DELETED:
            # Phase 22: authorize -> DELETING -> stop chat -> cleanup -> DELETED.
            document.status = DocumentStatus.DELETING
            db.commit()

            if bundle.settings.delete_dependent_chat == "delete":
                db.execute(
                    sql_text(
                        """
                        DELETE FROM message_sources
                        WHERE message_id IN (
                            SELECT m.id FROM messages m
                            JOIN sessions s ON s.id = m.session_id
                            WHERE s.document_id = :doc
                        )
                        """
                    ),
                    {"doc": document.id},
                )
                db.execute(
                    sql_text(
                        """
                        DELETE FROM messages
                        WHERE session_id IN (
                            SELECT id FROM sessions WHERE document_id = :doc
                        )
                        """
                    ),
                    {"doc": document.id},
                )
                db.execute(
                    sql_text("DELETE FROM sessions WHERE document_id = :doc"),
                    {"doc": document.id},
                )
            db.execute(
                sql_text("DELETE FROM processing_jobs WHERE document_id = :doc"),
                {"doc": document.id},
            )
            # Chunks + vectors on the request's own connection (never a
            # second pooled checkout — see vector_store.py).
            bundle.store.delete_document(db, document.id)
            try:
                bundle.storage.delete(document.storage_key)  # original binary
            except Exception:  # noqa: BLE001 — record cleanup failure, keep going
                log_event(
                    logger,
                    "storage cleanup failed",
                    level=40,
                    document_id=str(document.id),
                )
            document.status = DocumentStatus.DELETED
            db.commit()
            log_event(logger, "document deleted", document_id=str(document.id))

    return DeleteResponse(document_id=document_id, status=DocumentStatus.DELETED.value)
