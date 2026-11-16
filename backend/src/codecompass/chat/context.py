"""Prompt context: retrieved chunks as delimited untrusted data (FR-031, research R7, T142)."""

from __future__ import annotations

from html import escape

from langchain_core.documents import Document

from codecompass.guardrails.injection import UNTRUSTED_NOTE

HISTORY_EXCHANGES = 3
OLD_ANSWER_CHARS = 1600  # ~400 tokens


def format_chunks(docs: list[Document]) -> str:
    parts: list[str] = []
    for i, doc in enumerate(docs, start=1):
        m = doc.metadata
        attrs = f'id="{i}" path="{escape(m["path"])}" lines="{m["start_line"]}-{m["end_line"]}"'
        if m.get("injection_flag"):
            attrs += f' untrusted="{UNTRUSTED_NOTE}"'
        parts.append(f"<chunk {attrs}>\n{doc.page_content}\n</chunk>")
    return "\n\n".join(parts)


def format_history(messages: list[tuple[str, str]]) -> str:
    """`messages` are (role, content) pairs, oldest first; keeps the last few exchanges."""
    recent = messages[-HISTORY_EXCHANGES * 2 :]
    lines: list[str] = []
    for role, content in recent:
        if role == "assistant" and len(content) > OLD_ANSWER_CHARS:
            content = content[:OLD_ANSWER_CHARS] + " …"
        lines.append(f"{'User' if role == 'user' else 'Assistant'}: {content}")
    return "\n".join(lines) if lines else "(none)"
