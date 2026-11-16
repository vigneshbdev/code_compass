"""NFR-002: structure-aware chunking for Python and JS/TS (task T036)."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from codecompass.chunking import chunk_file
from codecompass.chunking.documents import ChunkDraft
from codecompass.chunking.treesitter_chunker import MAX_CHUNK_LINES, OVERLAP_LINES

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _chunks(rel: str) -> tuple[str, list[ChunkDraft]]:
    path = FIXTURES / rel
    text = path.read_text()
    return text, chunk_file(rel.split("/", 1)[1], text)


def _assert_line_invariant(text: str, chunks: list[ChunkDraft]) -> None:
    lines = text.splitlines(keepends=True)
    for c in chunks:
        assert 1 <= c.start_line <= c.end_line <= len(lines)
        assert c.text == "".join(lines[c.start_line - 1 : c.end_line]), c.symbol


def _by_symbol(chunks: list[ChunkDraft], symbol: str) -> ChunkDraft:
    return next(c for c in chunks if c.symbol == symbol)


def test_nfr002_python_decorated_function_includes_decorator_and_docstring() -> None:
    text, chunks = _chunks("mini_python_repo/app/api/users.py")
    read_user = _by_symbol(chunks, "read_user")
    assert read_user.kind == "function"
    assert read_user.text.startswith('@router.get("/{user_id}")')
    assert '"""Return one user."""' in read_user.text
    assert read_user.language == "python"
    _assert_line_invariant(text, chunks)


def test_nfr002_python_short_class_is_one_chunk() -> None:
    _, chunks = _chunks("mini_python_repo/app/api/users.py")
    service = _by_symbol(chunks, "UserService")
    assert service.kind == "class"
    assert "def create" in service.text and "def get" in service.text
    assert not any(c.symbol == "UserService.create" for c in chunks)


def test_nfr002_python_long_class_is_split_per_method_with_header() -> None:
    text, chunks = _chunks("mini_python_repo/app/api/users.py")
    methods = [c for c in chunks if c.symbol and c.symbol.startswith("ReportBuilder.")]
    assert len(methods) == 12
    first = _by_symbol(chunks, "ReportBuilder.report_1")
    assert first.kind == "method"
    assert first.symbol_leaf == "report_1"
    assert "class ReportBuilder" in first.embed_text  # class signature header
    assert all(c.end_line - c.start_line + 1 <= MAX_CHUNK_LINES for c in chunks)
    _assert_line_invariant(text, chunks)


def test_nfr002_python_module_level_code_becomes_module_chunks() -> None:
    _, chunks = _chunks("mini_python_repo/app/api/users.py")
    module = [c for c in chunks if c.kind == "module"]
    assert module, "imports and module-level statements must be indexed"
    assert any("from fastapi import APIRouter" in c.text for c in module)
    assert all(c.symbol is None for c in module)


def test_nfr002_leading_comment_is_attached() -> None:
    text = (
        "import os\n\n\n# Computes the answer.\n# Second line.\n"
        "def answer() -> int:\n    return 42\n"
    )
    chunks = chunk_file("calc.py", text)
    fn = _by_symbol(chunks, "answer")
    assert fn.text.startswith("# Computes the answer.")
    _assert_line_invariant(text, chunks)


def test_nfr002_oversized_function_is_split_with_overlap() -> None:
    body = "".join(f"    x{i} = {i}\n" for i in range(300))
    text = f"def huge() -> None:\n{body}"
    chunks = chunk_file("huge.py", text)
    pieces = [c for c in chunks if c.symbol == "huge"]
    assert len(pieces) >= 3
    assert all(c.end_line - c.start_line + 1 <= MAX_CHUNK_LINES for c in pieces)
    for a, b in itertools.pairwise(pieces):
        assert a.end_line - b.start_line + 1 == OVERLAP_LINES
    assert pieces[0].start_line == 1 and pieces[-1].end_line == 301
    _assert_line_invariant(text, chunks)


@pytest.mark.parametrize(
    ("rel", "language", "symbols"),
    [
        (
            "mini_ts_repo/src/components/ItemList.tsx",
            "tsx",
            {"useSelection", "formatItem", "ItemList", "ItemListProps"},
        ),
        ("mini_ts_repo/src/server.ts", "typescript", {"start"}),
        ("mini_ts_repo/src/utils/getUserById.js", "javascript", {"getUserById"}),
    ],
)
def test_nfr002_js_ts_symbols(rel: str, language: str, symbols: set[str]) -> None:
    text, chunks = _chunks(rel)
    assert symbols <= {c.symbol for c in chunks}
    assert {c.language for c in chunks} == {language}
    _assert_line_invariant(text, chunks)


def test_nfr002_every_line_is_covered() -> None:
    """No code is lost: every non-blank line belongs to at least one chunk."""
    for rel in ("mini_python_repo/app/api/users.py", "mini_ts_repo/src/server.ts"):
        text, chunks = _chunks(rel)
        covered = {n for c in chunks for n in range(c.start_line, c.end_line + 1)}
        for n, line in enumerate(text.splitlines(), start=1):
            if line.strip():
                assert n in covered, f"{rel}:{n} not in any chunk: {line!r}"
