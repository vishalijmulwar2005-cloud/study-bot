"""Centralized filename sanitization (audit fix B-1).

The stored/returned filename is a DISPLAY value only — storage always uses
server-generated random keys (see services/storage.py), so filesystem safety
never depends on this. Sanitization exists to satisfy the Security spec's
"safe filenames" requirement and to keep hostile names out of API responses.

Rules: strip control characters, cut to the final path segment (both / and \\),
remove Windows-illegal characters, collapse traversal dot-runs, normalize
whitespace, guard reserved device names, cap length while preserving the
extension, preserve safe Unicode, and fall back to `document.pdf`.
"""

from __future__ import annotations

import re
import unicodedata

MAX_FILENAME_LENGTH = 200
FALLBACK_FILENAME = "document.pdf"

# Windows-reserved device names (case-insensitive, with or without extension).
_RESERVED = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$", re.IGNORECASE
)
# Characters illegal on Windows filesystems (control chars handled separately).
_ILLEGAL_CHARS = re.compile(r'[<>:"|?*\x00-\x1f\x7f]')


def sanitize_filename(raw: str | None) -> str:
    """Return a safe display filename; never empty, always ends in .pdf
    when the input did."""
    if not raw:
        return FALLBACK_FILENAME

    name = unicodedata.normalize("NFC", raw)
    # Cut to the final path segment — defeats ../ and ..\ traversal entirely.
    name = re.split(r"[\\/]+", name)[-1]
    # Remove control and filesystem-illegal characters.
    name = _ILLEGAL_CHARS.sub("", name)
    # Collapse traversal dot-runs ("....", "..") to a single dot.
    name = re.sub(r"\.{2,}", ".", name)
    # Normalize whitespace runs and trim edges (including dot-only edges,
    # so names don't start/end with dots or spaces).
    name = re.sub(r"\s+", " ", name).strip().strip(". ")
    if not name:
        return FALLBACK_FILENAME
    if _RESERVED.match(name):
        name = f"_{name}"

    # Cap length while preserving the extension (if any).
    if "." in name:
        stem, _, ext = name.rpartition(".")
        ext = f".{ext}"[:16]
        max_stem = MAX_FILENAME_LENGTH - len(ext)
        if max_stem < 1:
            return FALLBACK_FILENAME
        name = stem[:max_stem] + ext
    elif len(name) > MAX_FILENAME_LENGTH:
        name = name[:MAX_FILENAME_LENGTH]

    return name or FALLBACK_FILENAME
