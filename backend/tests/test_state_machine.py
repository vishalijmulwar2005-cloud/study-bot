"""Document lifecycle state machine tests (Phase 4, spec §07)."""

from __future__ import annotations


from app.models import (
    DOCUMENT_TRANSITIONS,
    DocumentStatus,
    can_transition,
)


class TestDocumentStateMachine:
    def test_happy_path_uploaded_processing_ready(self):
        assert can_transition(DocumentStatus.UPLOADED, DocumentStatus.PROCESSING)
        assert can_transition(DocumentStatus.PROCESSING, DocumentStatus.READY)

    def test_processing_failure_and_retry(self):
        assert can_transition(DocumentStatus.PROCESSING, DocumentStatus.FAILED)
        assert can_transition(DocumentStatus.FAILED, DocumentStatus.PROCESSING)

    def test_deletion_path_from_all_active_states(self):
        for state in (
            DocumentStatus.UPLOADED,
            DocumentStatus.PROCESSING,
            DocumentStatus.READY,
            DocumentStatus.FAILED,
        ):
            assert can_transition(state, DocumentStatus.DELETING)
        assert can_transition(DocumentStatus.DELETING, DocumentStatus.DELETED)

    def test_deleted_is_terminal(self):
        assert DOCUMENT_TRANSITIONS[DocumentStatus.DELETED] == frozenset()

    def test_illegal_transitions_rejected(self):
        assert not can_transition(DocumentStatus.UPLOADED, DocumentStatus.READY)
        assert not can_transition(DocumentStatus.DELETED, DocumentStatus.PROCESSING)
        assert not can_transition(DocumentStatus.READY, DocumentStatus.UPLOADED)

    def test_transition_table_matches_spec_completeness(self):
        expected = {
            DocumentStatus.UPLOADED,
            DocumentStatus.PROCESSING,
            DocumentStatus.READY,
            DocumentStatus.FAILED,
            DocumentStatus.DELETING,
            DocumentStatus.DELETED,
        }
        assert set(DOCUMENT_TRANSITIONS) == expected
