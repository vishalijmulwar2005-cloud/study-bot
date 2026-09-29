"""Chunking with page/section metadata preservation (Phases 6, TRD §4).

Strategy (docs/DECISIONS.md #11): paragraph/sentence-aware recursive split
with overlap. Every chunk records page_start/page_end and, when a heading-like
line precedes it, a section label. Chunk indexes are assigned densely from 0
and uniqueness within a document is enforced by the DB.

Tokens are estimated at ~4 characters per token — good enough for sizing;
exact counts are not needed for correctness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.services.pdf_processor import PageText

_CHARS_PER_TOKEN = 4

_HEADING_RE = re.compile(
    r"^(?:"
    r"(?:chapter|section|part|appendix)\b.*"
    r"|\d+(?:\.\d+)*[.)]?\s+\S.*"
    r"|[IVXLC]+[.)]\s+\S.*"
    r")$",
    re.IGNORECASE,
)


@dataclass
class Block:
    page_number: int
    text: str
    is_heading: bool = False


@dataclass
class Chunk:
    chunk_index: int
    page_start: int
    page_end: int
    section: str | None
    text: str

    @property
    def token_count(self) -> int:
        return max(1, len(self.text) // _CHARS_PER_TOKEN)


@dataclass
class ChunkerConfig:
    target_tokens: int = 450
    overlap_tokens: int = 60

    @property
    def target_chars(self) -> int:
        return self.target_tokens * _CHARS_PER_TOKEN

    @property
    def overlap_chars(self) -> int:
        return self.overlap_tokens * _CHARS_PER_TOKEN


@dataclass
class _Accumulator:
    blocks: list[Block] = field(default_factory=list)
    section: str | None = None

    @property
    def length(self) -> int:
        return sum(len(b.text) + 2 for b in self.blocks)


class Chunker:
    def __init__(self, config: ChunkerConfig | None = None):
        self.config = config or ChunkerConfig()

    def chunk_pages(self, pages: list[PageText]) -> list[Chunk]:
        blocks = _build_blocks(pages)
        chunks: list[Chunk] = []
        acc = _Accumulator()

        def flush() -> None:
            if not acc.blocks:
                return
            text = "\n\n".join(b.text for b in acc.blocks).strip()
            if not text:
                acc.blocks = []
                return
            chunks.append(
                Chunk(
                    chunk_index=len(chunks),
                    page_start=acc.blocks[0].page_number,
                    page_end=acc.blocks[-1].page_number,
                    section=acc.section,
                    text=text,
                )
            )
            tail = _overlap_tail(acc.blocks, self.config.overlap_chars)
            acc.blocks = list(tail)

        for block in blocks:
            if block.is_heading:
                acc.section = block.text[:256]
            if acc.length + len(block.text) + 2 > self.config.target_chars and acc.blocks:
                flush()
            if len(block.text) > self.config.target_chars:
                # Oversized single block: sentence-split it.
                for piece in _split_long_block(block, self.config.target_chars):
                    if acc.length + len(piece.text) + 2 > self.config.target_chars and acc.blocks:
                        flush()
                    acc.blocks.append(piece)
            else:
                acc.blocks.append(block)
        flush()
        return chunks


def _build_blocks(pages: list[PageText]) -> list[Block]:
    """Split page text into paragraph blocks, tagging heading-like lines."""
    blocks: list[Block] = []
    for page in pages:
        for paragraph in re.split(r"\n\s*\n", page.text):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            lines = [ln.strip() for ln in paragraph.splitlines() if ln.strip()]
            if len(lines) == 1 and _HEADING_RE.match(lines[0]) and len(lines[0]) < 120:
                blocks.append(Block(page.page_number, lines[0], is_heading=True))
                continue
            blocks.append(Block(page.page_number, paragraph))
    return blocks


def _overlap_tail(blocks: list[Block], overlap_chars: int) -> list[Block]:
    """Carry trailing blocks into the next chunk for overlap continuity."""
    if overlap_chars <= 0:
        return []
    tail: list[Block] = []
    total = 0
    for block in reversed(blocks):
        total += len(block.text) + 2
        tail.append(block)
        if total >= overlap_chars:
            break
    tail.reverse()
    return tail


def _split_long_block(block: Block, target_chars: int) -> list[Block]:
    sentences = re.split(r"(?<=[.!?])\s+", block.text)
    pieces: list[Block] = []
    current: list[str] = []
    length = 0
    for sentence in sentences:
        if length + len(sentence) + 1 > target_chars and current:
            pieces.append(Block(block.page_number, " ".join(current)))
            current, length = [], 0
        current.append(sentence)
        length += len(sentence) + 1
    if current:
        pieces.append(Block(block.page_number, " ".join(current)))
    return pieces or [block]
