"""NFR-002: generic chunking for non-code text files (task T037)."""

from __future__ import annotations

from codecompass.chunking import chunk_file
from codecompass.chunking.generic_chunker import WINDOW_LINES, WINDOW_OVERLAP


def _invariant(text: str, chunks) -> None:  # type: ignore[no-untyped-def]
    lines = text.splitlines(keepends=True)
    for c in chunks:
        assert c.text == "".join(lines[c.start_line - 1 : c.end_line])


def test_nfr002_markdown_split_at_headings() -> None:
    text = "# Title\n\nIntro.\n\n## Running\n\nRun it.\n\n## Config\n\nSet KEY=VALUE.\n"
    chunks = chunk_file("README.md", text)
    assert [c.kind for c in chunks] == ["section"] * 3
    assert [c.symbol for c in chunks] == ["Title", "Running", "Config"]
    assert chunks[1].text.startswith("## Running")
    _invariant(text, chunks)


def test_nfr002_other_text_uses_overlapping_windows() -> None:
    text = "".join(f"line {i}\n" for i in range(1, 151))
    chunks = chunk_file("data/settings.yaml", text)
    assert all(c.kind == "window" for c in chunks)
    step = WINDOW_LINES - WINDOW_OVERLAP
    assert [(c.start_line, c.end_line) for c in chunks] == [
        (1, 60),
        (1 + step, 60 + step),
        (1 + 2 * step, 150),
    ]
    assert chunks[0].language == "yaml"
    _invariant(text, chunks)


def test_nfr002_short_file_is_one_window() -> None:
    chunks = chunk_file("Dockerfile", 'FROM python:3.12\nCMD ["x"]\n')
    assert len(chunks) == 1 and chunks[0].start_line == 1 and chunks[0].end_line == 2


def test_nfr002_empty_file_has_no_chunks() -> None:
    assert chunk_file("empty.txt", "") == []
    assert chunk_file("blank.md", "\n\n") == []


def test_nfr002_embed_text_has_path_header() -> None:
    chunk = chunk_file("docs/guide.md", "# Guide\n\nHello.\n")[0]
    assert chunk.embed_text.startswith("# path: docs/guide.md\n")
    assert chunk.token_count > 0
