"""Session + message endpoints (Phases 11–12; API contract §09, §11).

POST /api/v1/sessions                     create a document-scoped session
GET  /api/v1/sessions/{id}/messages       load ordered conversation
POST /api/v1/sessions/{id}/messages       ask a question (full RAG pipeline)

Every route re-verifies ownership server-side; client-supplied IDs are
identifiers, never proof of permission (Phase 20).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_bundle, get_db_session, get_identity, rate_limit
from app.bundle import ServiceBundle
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger, log_event
from app.core.security import Identity, ensure_owner_or_404
from app.database import (
    ChatSession,
    Document,
    Message,
    MessageSource,
)
from app.models import DocumentStatus
from app.schemas import (
    AskRequest,
    AskResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    MessageOut,
    MessagesResponse,
    SourceOut,
)
from app.services.chat_pipeline import ask_question

router = APIRouter(prefix="/api/v1/sessions", tags=["sessions"])
logger = get_logger("app.api.sessions")


def _load_owned_session(
    db: Session, session_id: uuid.UUID, identity: Identity
) -> tuple[ChatSession, Document]:
    chat_session = db.get(ChatSession, session_id)
    if chat_session is None:
        raise AppError(ErrorCode.NOT_FOUND)
    ensure_owner_or_404(identity, chat_session.session_id, "session")
    document = db.get(Document, chat_session.document_id)
    if document is None or document.status == DocumentStatus.DELETED:
        raise AppError(ErrorCode.NOT_FOUND)
    ensure_owner_or_404(identity, document.session_id, "document")
    return chat_session, document


def _serialize_message(message: Message, sources: list[MessageSource]) -> MessageOut:
    return MessageOut(
        message_id=message.id,
        role=message.role.value.lower(),
        content=message.content,
        status=message.status.value,
        created_at=message.created_at.isoformat(),
        sources=[
            SourceOut(
                chunk_id=s.chunk_id, page=s.page, relevance_score=s.relevance_score
            )
            for s in sources
        ],
    )


@router.post("", response_model=CreateSessionResponse, status_code=201)
def create_session(
    payload: CreateSessionRequest,
    db: Session = Depends(get_db_session),
    bundle: ServiceBundle = Depends(get_bundle),
    identity: Identity = Depends(get_identity),
) -> CreateSessionResponse:
    document = db.get(Document, payload.document_id)
    if document is None or document.status == DocumentStatus.DELETED:
        raise AppError(ErrorCode.NOT_FOUND)
    ensure_owner_or_404(identity, document.session_id, "document")
    if document.status != DocumentStatus.READY:
        # Phase 4: only READY documents accept Q&A.
        raise AppError(
            ErrorCode.INVALID_REQUEST,
            "The document is not ready for questions yet.",
        )
    chat_session = ChatSession(
        document_id=document.id, session_id=identity.token_hash
    )
    db.add(chat_session)
    db.commit()
    return CreateSessionResponse(
        session_id=chat_session.id, document_id=document.id
    )


@router.get("/{session_id}/messages", response_model=MessagesResponse)
def list_messages(
    session_id: uuid.UUID,
    db: Session = Depends(get_db_session),
    identity: Identity = Depends(get_identity),
) -> MessagesResponse:
    chat_session, document = _load_owned_session(db, session_id, identity)
    messages = db.execute(
        select(Message)
        .where(Message.session_id == chat_session.id)
        .order_by(Message.created_at)
    ).scalars().all()
    sources = db.execute(
        select(MessageSource)
        .where(MessageSource.message_id.in_([m.id for m in messages] or [uuid.uuid4()]))
    ).scalars().all()
    sources_by_message: dict[uuid.UUID, list[MessageSource]] = {}
    for source in sources:
        sources_by_message.setdefault(source.message_id, []).append(source)
    return MessagesResponse(
        session_id=chat_session.id,
        document_id=document.id,
        messages=[
            _serialize_message(m, sources_by_message.get(m.id, [])) for m in messages
        ],
    )


@router.post(
    "/{session_id}/messages",
    response_model=AskResponse,
    dependencies=[Depends(rate_limit("chat", "rate_limit_chat_per_min"))],
)
async def ask(
    session_id: uuid.UUID,
    payload: AskRequest,
    db: Session = Depends(get_db_session),
    bundle: ServiceBundle = Depends(get_bundle),
    identity: Identity = Depends(get_identity),
) -> AskResponse:
    chat_session, document = _load_owned_session(db, session_id, identity)
    if document.status != DocumentStatus.READY:
        raise AppError(
            ErrorCode.INVALID_REQUEST, "The document is not ready for questions."
        )

    log_event(
        logger,
        "question received",
        session_id=str(chat_session.id),
        document_id=str(document.id),
        length=len(payload.question),
    )

    result = await ask_question(
        db=db,
        chat_session=chat_session,
        document=document,
        question=payload.question,
        retriever=bundle.retriever,
        llm=bundle.llm,
        settings=bundle.settings,
    )
    return AskResponse(
        message_id=result.message_id,
        answer=result.answer,
        grounded=result.grounded,
        sources=[
            SourceOut(
                chunk_id=s.chunk_id, page=s.page, relevance_score=s.relevance_score
            )
            for s in result.sources
        ],
    )
