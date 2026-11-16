"""Citation parsing, validation and answer status (FR-011, FR-013, C4, research R7, task T142)."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from langchain_core.documents import Document

NOT_FOUND = "I couldn't find this in the codebase."
CITATION = re.compile(r"\[([\w./\-]+):(\d+)(?:-(\d+))?\]")


@dataclass(frozen=True)
class Citation:
    path: str
    start_line: int
    end_line: int
    chunk_id: int | None
    content_hash: str
    ordinal: int


def _cited_text(doc: Document, start: int, end: int) -> str:
    lines = doc.page_content.splitlines(keepends=True)
    offset = int(doc.metadata["start_line"])
    return "".join(lines[start - offset : end - offset + 1])


def validate(text: str, packed: list[Document]) -> tuple[list[Citation], int]:
    """(valid citations in order of first appearance, number of invalid citations)."""
    valid: list[Citation] = []
    seen: set[tuple[str, int, int]] = set()
    invalid = 0
    for match in CITATION.finditer(text):
        path, start = match.group(1), int(match.group(2))
        end = int(match.group(3) or start)
        if end < start or (path, start, end) in seen:
            invalid += end < start
            continue
        doc = next(
            (
                d
                for d in packed
                if d.metadata["path"] == path
                and int(d.metadata["start_line"]) <= start
                and end <= int(d.metadata["end_line"])
            ),
            None,
        )
        if doc is None:
            invalid += 1
            continue
        seen.add((path, start, end))
        digest = hashlib.sha256(_cited_text(doc, start, end).encode()).hexdigest()
        valid.append(Citation(path, start, end, doc.metadata.get("chunk_id"), digest, len(valid)))
    return valid, invalid


def answer_status(text: str, valid: list[Citation]) -> str:
    """`not_found` for the exact sentence, `unverified` for claims without a valid citation."""
    if text.strip().rstrip(".") == NOT_FOUND.rstrip(".") or text.strip().startswith(NOT_FOUND):
        return "not_found"
    return "complete" if valid else "unverified"
