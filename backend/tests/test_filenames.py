"""B-1 filename sanitization tests (Phase 2 of the fix plan)."""

from __future__ import annotations

from app.core.filenames import FALLBACK_FILENAME, MAX_FILENAME_LENGTH, sanitize_filename


class TestFilenameSanitization:
    def test_path_traversal_unix(self):
        assert sanitize_filename("../../etc/passwd.pdf") == "passwd.pdf"

    def test_path_traversal_windows(self):
        assert sanitize_filename("..\\..\\evil.pdf") == "evil.pdf"

    def test_mixed_dots_and_separators(self):
        assert sanitize_filename("....//evil.pdf") == "evil.pdf"
        assert sanitize_filename("..\\....//deep.pdf") == "deep.pdf"

    def test_control_characters_removed(self):
        assert sanitize_filename("no\x00te\x1b.pdf") == "note.pdf"

    def test_very_long_filename_capped_preserving_extension(self):
        name = "x" * 300 + ".pdf"
        result = sanitize_filename(name)
        assert len(result) == MAX_FILENAME_LENGTH
        assert result.endswith(".pdf")

    def test_unicode_filename_preserved(self):
        assert sanitize_filename("日本語 ノート.pdf") == "日本語 ノート.pdf"
        assert sanitize_filename("café notes.pdf") == "café notes.pdf"

    def test_empty_and_none_fall_back(self):
        assert sanitize_filename("") == FALLBACK_FILENAME
        assert sanitize_filename(None) == FALLBACK_FILENAME
        assert sanitize_filename("   ") == FALLBACK_FILENAME
        assert sanitize_filename("...") == FALLBACK_FILENAME

    def test_spaces_normalized(self):
        assert sanitize_filename("  my   notes  .pdf ") == "my notes .pdf"

    def test_special_characters_removed(self):
        assert sanitize_filename('a<b>c:d"e|f?g*h.pdf') == "abcdefgh.pdf"

    def test_double_extension_preserved(self):
        assert sanitize_filename("notes.backup.pdf") == "notes.backup.pdf"

    def test_html_looking_filename_neutralized(self):
        result = sanitize_filename("<img src=x onerror=alert(1)>.pdf")
        assert "<" not in result and ">" not in result

    def test_windows_reserved_names_prefixed(self):
        assert sanitize_filename("CON.pdf") == "_CON.pdf"
        assert sanitize_filename("NUL") == "_NUL"

    def test_extension_preserved_case_insensitive(self):
        assert sanitize_filename("Report.PDF") == "Report.PDF"

    def test_no_extension_gets_none_added(self):
        # sanitizer does not invent extensions; validation layer enforces .pdf
        assert sanitize_filename("just-a-name") == "just-a-name"

    def test_fallback_ends_with_pdf(self):
        assert FALLBACK_FILENAME == "document.pdf"
