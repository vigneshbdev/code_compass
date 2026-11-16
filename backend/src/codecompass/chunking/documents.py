"""Chunk drafts produced by the chunkers, convertible to LangChain Documents (task T048)."""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.documents import Document

from codecompass.chunking.identifiers import split_identifiers

CHARS_PER_TOKEN = 4  # rough estimate; used only for context-budget packing


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def embed_header(path: str, symbol: str | None, parent: str | None) -> str:
    """Context header prepended to the text that gets embedded (research R4)."""
    header = f"# path: {path}\n"
    if symbol:
        header += f"# symbol: {symbol}\n"
    if parent:
        header += f"# in: {parent}\n"
    return header


@dataclass
class ChunkDraft:
    path: str
    start_line: int
    end_line: int
    language: str
    kind: str
    text: str
    symbol: str | None = None
    parent: str | None = None  # enclosing class signature, for method chunks
    embed_text: str = field(init=False)
    identifiers: str = field(init=False)
    token_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.embed_text = embed_header(self.path, self.symbol, self.parent) + self.text
        self.identifiers = split_identifiers(f"{self.symbol or ''} {self.text}")
        self.token_count = estimate_tokens(self.text)

    @property
    def symbol_leaf(self) -> str | None:
        return self.symbol.rsplit(".", 1)[-1] if self.symbol else None

    def to_document(self) -> Document:
        return Document(
            page_content=self.text,
            metadata={
                "path": self.path,
                "start_line": self.start_line,
                "end_line": self.end_line,
                "language": self.language,
                "kind": self.kind,
                "symbol": self.symbol,
                "symbol_leaf": self.symbol_leaf,
            },
        )


def line_slice(lines: list[str], start: int, end: int) -> str:
    """Text of 1-based inclusive lines start..end."""
    return "".join(lines[start - 1 : end])
