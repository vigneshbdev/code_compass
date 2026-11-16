"""FR-015: identifiers are split so keyword search finds them (task T038)."""

from __future__ import annotations

import pytest

from codecompass.chunking.identifiers import split_identifiers


@pytest.mark.parametrize(
    ("text", "must_contain"),
    [
        ("parse_config", ["parse_config", "parse", "config"]),
        ("getUserById", ["getUserById", "get", "user", "by", "id"]),
        ("HTTPServer", ["HTTPServer", "http", "server"]),
        ("app.core.config", ["app.core.config", "app", "core", "config"]),
        ("XMLHttpRequest2", ["XMLHttpRequest2", "xml", "http", "request"]),
    ],
)
def test_fr015_split_identifiers(text: str, must_contain: list[str]) -> None:
    tokens = split_identifiers(text).split()
    for token in must_contain:
        assert token in tokens


def test_fr015_plain_words_are_not_duplicated() -> None:
    assert split_identifiers("hello world").split() == ["hello", "world"]


def test_fr015_only_code_identifiers_are_expanded() -> None:
    tokens = split_identifiers("def parse_config(path): return 1").split()
    assert "parse_config" in tokens and "parse" in tokens and "config" in tokens
    assert "return" in tokens
