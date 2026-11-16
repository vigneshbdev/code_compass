"""Generic chunking for non-code text (NFR-002, research R4, task T050).

Markdown is split at headings; everything else into 60-line windows with a 10-line overlap.
"""

from __future__ import annotations

import re

from codecompass.chunking.documents import ChunkDraft, line_slice

WINDOW_LINES = 60
WINDOW_OVERLAP = 10
MAX_SECTION_LINES = 120
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def windows(start: int, end: int, size: int, overlap: int) -> list[tuple[int, int]]:
    """1-based inclusive line windows covering start..end."""
    spans: list[tuple[int, int]] = []
    first = start
    while True:
        last = min(first + size - 1, end)
        spans.append((first, last))
        if last >= end:
            return spans
        first = last - overlap + 1


def _is_blank(text: str) -> bool:
    return not text.strip()


def chunk_windows(path: str, text: str, language: str) -> list[ChunkDraft]:
    lines = text.splitlines(keepends=True)
    if _is_blank(text):
        return []
    return [
        ChunkDraft(path, s, e, language, "window", line_slice(lines, s, e))
        for s, e in windows(1, len(lines), WINDOW_LINES, WINDOW_OVERLAP)
        if not _is_blank(line_slice(lines, s, e))
    ]


def chunk_markdown(path: str, text: str) -> list[ChunkDraft]:
    lines = text.splitlines(keepends=True)
    if _is_blank(text):
        return []
    starts: list[tuple[int, str | None]] = []
    in_fence = False
    for n, line in enumerate(lines, start=1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else HEADING.match(line.rstrip("\n"))
        if match:
            starts.append((n, match.group(2)))
    if not starts or starts[0][0] != 1:
        starts.insert(0, (1, None))  # preamble before the first heading

    chunks: list[ChunkDraft] = []
    for i, (start, title) in enumerate(starts):
        end = starts[i + 1][0] - 1 if i + 1 < len(starts) else len(lines)
        for s, e in windows(start, end, MAX_SECTION_LINES, WINDOW_OVERLAP):
            body = line_slice(lines, s, e)
            if not _is_blank(body):
                chunks.append(ChunkDraft(path, s, e, "markdown", "section", body, symbol=title))
    return chunks
