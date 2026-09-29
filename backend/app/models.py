"""Domain enums and the document lifecycle state machine.

Document lifecycle (Database & API Specification §07):

    UPLOADED  -> PROCESSING, DELETING
    PROCESSING -> READY, FAILED, DELETING
    READY     -> DELETING, PROCESSING (re-index after retry)
    FAILED    -> PROCESSING (retry), DELETING
    DELETING  -> DELETED
    DELETED   -> terminal; access denied
"""

from __future__ import annotations

import enum


class DocumentStatus(str, enum.Enum):
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"
    DELETING = "DELETING"
    DELETED = "DELETED"


class JobStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class JobStage(str, enum.Enum):
    QUEUED = "QUEUED"
    EXTRACT = "EXTRACT"
    CHUNK = "CHUNK"
    EMBED = "EMBED"
    INDEX = "INDEX"
    DONE = "DONE"


class SessionStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MessageRole(str, enum.Enum):
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class MessageStatus(str, enum.Enum):
    COMPLETE = "COMPLETE"
    NO_EVIDENCE = "NO_EVIDENCE"
    ERROR = "ERROR"


class FeedbackRating(str, enum.Enum):
    UP = "up"
    DOWN = "down"


# Allowed document status transitions, straight from spec §07.
DOCUMENT_TRANSITIONS: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.UPLOADED: frozenset({DocumentStatus.PROCESSING, DocumentStatus.DELETING}),
    DocumentStatus.PROCESSING: frozenset(
        {DocumentStatus.READY, DocumentStatus.FAILED, DocumentStatus.DELETING}
    ),
    # READY -> PROCESSING covers "retry/re-index" after a config change.
    DocumentStatus.READY: frozenset({DocumentStatus.DELETING, DocumentStatus.PROCESSING}),
    DocumentStatus.FAILED: frozenset({DocumentStatus.PROCESSING, DocumentStatus.DELETING}),
    DocumentStatus.DELETING: frozenset({DocumentStatus.DELETED}),
    DocumentStatus.DELETED: frozenset(),
}


def can_transition(current: DocumentStatus, target: DocumentStatus) -> bool:
    return target in DOCUMENT_TRANSITIONS[current]


class InvalidTransitionError(ValueError):
    """Raised when a document status change violates the state machine."""

    def __init__(self, current: DocumentStatus, target: DocumentStatus) -> None:
        super().__init__(f"Illegal document transition {current.value} -> {target.value}")
        self.current = current
        self.target = target
