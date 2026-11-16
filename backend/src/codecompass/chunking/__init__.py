"""Chunking entry point: structure-aware for code, generic for everything else (NFR-002)."""

from __future__ import annotations

import logging
from pathlib import PurePosixPath

from codecompass.chunking.documents import ChunkDraft
from codecompass.chunking.generic_chunker import chunk_markdown, chunk_windows
from codecompass.chunking.treesitter_chunker import CODE_LANGUAGES, chunk_code

logger = logging.getLogger(__name__)

EXTENSION_LANGUAGE = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".md": "markdown",
    ".mdx": "markdown",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".json": "json",
    ".ini": "ini",
    ".sql": "sql",
    ".sh": "shell",
    ".html": "html",
    ".css": "css",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".txt": "text",
    ".env": "dotenv",
}
FILENAME_LANGUAGE = {"Dockerfile": "dockerfile", "Makefile": "makefile", ".env": "dotenv"}


def detect_language(path: str) -> str:
    p = PurePosixPath(path)
    if p.name in FILENAME_LANGUAGE:
        return FILENAME_LANGUAGE[p.name]
    if p.name.startswith(".env"):
        return "dotenv"
    return EXTENSION_LANGUAGE.get(p.suffix.lower(), "text")


def chunk_file(path: str, text: str) -> list[ChunkDraft]:
    language = detect_language(path)
    if language in CODE_LANGUAGES:
        try:
            return chunk_code(path, text, language)
        except Exception:  # a parser problem must never lose the file
            logger.exception(
                "tree-sitter chunking failed; using windows", extra={"data": {"path": path}}
            )
            return chunk_windows(path, text, language)
    if language == "markdown":
        return chunk_markdown(path, text)
    return chunk_windows(path, text, language)
