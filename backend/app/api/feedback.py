"""Answer feedback endpoint (API contract §09; feedback table)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_db_session, get_identity
from app.core.errors import AppError, ErrorCode
from app.core.security import Identity, ensure_owner_or_404
from app.database import ChatSession, Document, Feedback, Message
from app.models import FeedbackRating
from app.schemas import FeedbackRequest, FeedbackResponse

router = APIRouter(prefix="/api/v1/messages", tags=["feedback"])


@router.post("/{message_id}/feedback", response_model=FeedbackResponse, status_code=201)
def submit_feedback(
    message_id: uuid.UUID,
    payload: FeedbackRequest,
    db: Session = Depends(get_db_session),
    identity: Identity = Depends(get_identity),
) -> FeedbackResponse:
    message = db.get(Message, message_id)
    if message is None:
        raise AppError(ErrorCode.NOT_FOUND)
    chat_session = db.get(ChatSession, message.session_id)
    if chat_session is None:
        raise AppError(ErrorCode.NOT_FOUND)
    document = db.get(Document, chat_session.document_id)
    if document is None:
        raise AppError(ErrorCode.NOT_FOUND)
    ensure_owner_or_404(identity, document.session_id, "message")

    existing = db.execute(
        select(Feedback).where(Feedback.message_id == message.id)
    ).scalar_one_or_none()
    if existing is not None:
        existing.rating = FeedbackRating(payload.rating)
        existing.reason = payload.reason
        feedback = existing
    else:
        feedback = Feedback(
            message_id=message.id,
            rating=FeedbackRating(payload.rating),
            reason=payload.reason,
        )
        db.add(feedback)
    db.commit()
    return FeedbackResponse(message_id=message.id, rating=feedback.rating.value)
