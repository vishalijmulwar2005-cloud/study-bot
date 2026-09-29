"""Chat pipeline: ask a question against one active document (Phases 7–12).

Server-side sequence per the implementation contract (Phase 11):
    authorize -> verify session/document relationship -> verify READY ->
    retrieve conversation context -> document-scoped retrieval ->
    evidence gate -> (only if sufficient) LLM -> validate sources ->
    persist message/source records -> return response.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger, log_event
from app.database import ChatSession, Document, Message, MessageRole, MessageStatus, MessageSource
from app.services.embeddings import ProviderUnavailable
from app.services.llm import LLMService
from app.services.prompts import build_generation_messages
from app.services.retriever import (
    NO_EVIDENCE_ANSWER,
    EvidenceDecision,
    Retriever,
    evaluate_evidence,
    log_retrieval_event,
)
from app.services.source_validator import ValidatedSource, validate_sources

logger = get_logger("app.chat")

MAX_QUESTION_CHARS = 2000
HISTORY_TURNS = 6

# --- B-2: deterministic follow-up reformulation -----------------------------
# When a short, anaphoric question ("Explain that in simple words.") fails the
# evidence gate, retrieval is retried with a reformulated query built from the
# conversation. The gate itself is untouched: same threshold, same
# document scope, deterministic decision — and the LLM is still never asked
# whether evidence exists. Long or lexically rich questions (e.g. cross-document
# bait) never take the fallback path, preserving audit case 8.2 semantics.

ANAPHORA_HINT_RE = re.compile(
    r"\b(that|this|it|those|these|them|explain|elaborate|simpler|"
    r"simple words|more|again|previous|above|why|summarize)\b",
    re.IGNORECASE,
)
MAX_FOLLOWUP_WORDS = 8
REFORMULATED_ANSWER_CHARS = 300


def is_dependent_followup(question: str) -> bool:
    """True when the question is short AND references prior conversation."""
    return len(question.split()) <= MAX_FOLLOWUP_WORDS and bool(
        ANAPHORA_HINT_RE.search(question)
    )


def build_reformulated_query(
    question: str, history: list[dict[str, str]]
) -> str | None:
    """Build 'previous question + current question (+ prior answer excerpt)'
    for a second retrieval attempt, or None when not applicable."""
    if not is_dependent_followup(question):
        return None
    last_user = next(
        (h["content"] for h in reversed(history) if h.get("role") == "user"),
        None,
    )
    if not last_user or last_user.strip() == question.strip():
        return None
    parts = [last_user.strip(), question.strip()]
    last_assistant = next(
        (h["content"] for h in reversed(history) if h.get("role") == "assistant"),
        None,
    )
    if last_assistant:
        parts.append(last_assistant[:REFORMULATED_ANSWER_CHARS])
    return "\n".join(p for p in parts if p) or None


@dataclass(frozen=True)
class AnswerResult:
    message_id: uuid.UUID
    answer: str
    grounded: bool
    sources: list[ValidatedSource]
    status: MessageStatus


def load_conversation_history(db: Session, session_id: uuid.UUID, exclude_message_id: uuid.UUID) -> list[dict[str, str]]:
    """Recent turns for follow-up resolution — content stays inside the
    pipeline and is never logged."""
    rows = db.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.id != exclude_message_id)
        .order_by(Message.created_at.desc())
        .limit(HISTORY_TURNS)
    ).scalars().all()
    return [{"role": m.role.value.lower(), "content": m.content} for m in reversed(rows)]


async def ask_question(
    db: Session,
    chat_session: ChatSession,
    document: Document,
    question: str,
    retriever: Retriever,
    llm: LLMService,
    settings,
) -> AnswerResult:
    if not question or not question.strip():
        raise AppError(ErrorCode.INVALID_REQUEST, "The question field is required.")
    question = question.strip()[:MAX_QUESTION_CHARS]

    user_message = Message(
        session_id=chat_session.id, role=MessageRole.USER, content=question
    )
    db.add(user_message)
    db.commit()

    history = load_conversation_history(db, chat_session.id, user_message.id)

    # Document-scoped retrieval on the request's own connection (the vector
    # query must never check out a second pooled connection — see
    # vector_store.py). The db.commit() afterwards releases that connection
    # so nothing is held across the LLM call below.
    candidates = await retriever.retrieve(db, document.id, question, settings.retrieval_top_k)
    decision: EvidenceDecision = evaluate_evidence(candidates, settings.evidence_threshold)

    # B-2: one deterministic retry with a conversation-aware query, only for
    # short anaphoric follow-ups that failed the gate. Threshold and scope
    # are identical on the second attempt.
    reformulated = False
    if not decision.sufficient:
        reformulated_query = build_reformulated_query(question, history)
        if reformulated_query:
            alt = await retriever.retrieve(
                db, document.id, reformulated_query, settings.retrieval_top_k
            )
            alt_decision = evaluate_evidence(alt, settings.evidence_threshold)
            if alt_decision.sufficient:
                candidates, decision = alt, alt_decision
                reformulated = True

    log_retrieval_event(
        "app.chat", document.id, decision, settings.retrieval_top_k,
        reformulated=reformulated,
    )
    db.commit()

    if not decision.sufficient:
        # Phase 8/17: no LLM call; product no-evidence response, no sources.
        message = Message(
            session_id=chat_session.id,
            role=MessageRole.ASSISTANT,
            content=NO_EVIDENCE_ANSWER,
            status=MessageStatus.NO_EVIDENCE,
        )
        db.add(message)
        db.commit()
        return AnswerResult(
            message_id=message.id,
            answer=NO_EVIDENCE_ANSWER,
            grounded=False,
            sources=[],
            status=MessageStatus.NO_EVIDENCE,
        )

    if not llm.configured:
        # Honest blocker: never generate from general knowledge, never fake.
        raise ProviderUnavailable(ErrorCode.LLM_NOT_CONFIGURED)

    messages_for_llm = build_generation_messages(question, history, candidates)
    try:
        answer_text = await llm.complete(messages_for_llm, settings.llm_max_output_tokens)
    except ProviderUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 — provider failures are all the same to clients
        log_event(logger, "llm call failed", level=40, detail=exc.__class__.__name__)
        raise ProviderUnavailable(ErrorCode.LLM_PROVIDER_FAILED) from exc

    answer_text = (answer_text or "").strip() or NO_EVIDENCE_ANSWER

    # Phase 10: sources come from retrieval metadata, validated against the
    # active document — never from model output.
    sources = validate_sources(candidates, document.id)

    # Defense in depth: if the model itself concluded the evidence was
    # insufficient (it echoes the no-evidence sentence), the product promise
    # wins — no grounded flag, no source chips, even though the gate passed.
    if answer_text == NO_EVIDENCE_ANSWER:
        log_event(logger, "llm returned no-evidence response")
        sources = []

    message = Message(
        session_id=chat_session.id,
        role=MessageRole.ASSISTANT,
        content=answer_text,
        status=MessageStatus.NO_EVIDENCE if not sources else MessageStatus.COMPLETE,
    )
    db.add(message)
    db.flush()
    for source in sources:
        db.add(
            MessageSource(
                message_id=message.id,
                chunk_id=source.chunk_id,
                page=source.page,
                relevance_score=source.relevance_score,
            )
        )
    db.commit()
    grounded = bool(sources)
    return AnswerResult(
        message_id=message.id,
        answer=answer_text,
        grounded=grounded,
        sources=sources,
        status=message.status,
    )
