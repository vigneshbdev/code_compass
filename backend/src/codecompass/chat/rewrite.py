"""Follow-up rewriting and identifier extraction (FR-014, FR-015, research R6, task T142)."""

from __future__ import annotations

import logging
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

IDENTIFIER_PATTERNS = (
    re.compile(r"`([^`\s]{2,80})`"),  # backticked
    re.compile(r"\b([A-Za-z_][A-Za-z0-9]*_[A-Za-z0-9_]+)\b"),  # snake_case
    re.compile(r"\b([a-z]+[A-Z][A-Za-z0-9]*)\b"),  # camelCase
    re.compile(r"\b([A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*)\b"),  # PascalCase with 2+ humps
    re.compile(r"\b([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+)\b"),  # dotted.names / file.py
    re.compile(r"\b([A-Za-z_]\w*)\(\)"),  # call()
)


def extract_identifiers(text: str) -> list[str]:
    """Deterministic identifier extraction, so FR-015 never depends on the LLM."""
    found: dict[str, None] = {}
    for pattern in IDENTIFIER_PATTERNS:
        for match in pattern.finditer(text):
            found.setdefault(match.group(1).strip("()"), None)
    return list(found)


class Rewrite(BaseModel):
    standalone_question: str
    identifiers: list[str] = Field(default_factory=list)


async def rewrite_question(
    model: BaseChatModel,
    template: ChatPromptTemplate,
    question: str,
    history: str,
    config: RunnableConfig | None = None,
) -> Rewrite:
    """Standalone question + identifiers. Without history, no LLM call is made."""
    regex_ids = extract_identifiers(question)
    if not history.strip():
        return Rewrite(standalone_question=question, identifiers=regex_ids)
    try:
        chain = template | model.with_structured_output(Rewrite)
        result = await chain.ainvoke({"history": history, "question": question}, config=config)
        rewritten = result if isinstance(result, Rewrite) else Rewrite.model_validate(result)
    except Exception:
        logger.warning("rewrite failed; using the question as asked", exc_info=True)
        return Rewrite(standalone_question=question, identifiers=regex_ids)
    merged = list(
        dict.fromkeys(
            [
                *regex_ids,
                *extract_identifiers(rewritten.standalone_question),
                *rewritten.identifiers,
            ]
        )
    )
    return Rewrite(
        standalone_question=rewritten.standalone_question or question, identifiers=merged
    )
