"""Starter questions for the overview (FR-021, task T149)."""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from codecompass.observability.prompt_sync import PromptRegistry

logger = logging.getLogger(__name__)
MIN_QUESTIONS, MAX_QUESTIONS = 3, 5


class Starters(BaseModel):
    questions: list[str] = Field(default_factory=list)


def template_questions(overview: dict[str, Any]) -> list[str]:
    """Deterministic fallback built from the overview facts."""
    questions = ["What does this codebase do, and how is it organised?"]
    runtime = [d["name"] for d in overview.get("dependencies", []) if not d.get("dev")]
    for name in runtime[:2]:
        questions.append(f"How is {name} used in this codebase?")
    langs = [row["language"] for row in overview.get("languages", [])]
    if langs:
        questions.append(f"Where is the main entry point of the {langs[0]} code?")
    questions.append("How are the tests organised and run?")
    return questions[:MAX_QUESTIONS]


def _summary(overview: dict[str, Any]) -> str:
    deps = [
        f"{d['name']} ({d['ecosystem']}{', dev' if d.get('dev') else ''})"
        for d in overview.get("dependencies", [])
    ]
    return json.dumps({"languages": overview.get("languages", [])[:6], "dependencies": deps[:40]})


async def starter_questions(
    model: BaseChatModel,
    overview: dict[str, Any],
    prompts: PromptRegistry | None = None,
    config: RunnableConfig | None = None,
) -> tuple[list[str], str]:
    """(questions, "llm" | "template"). Never raises: falls back to templates."""
    try:
        template = (prompts or PromptRegistry()).get("starter_questions").template
        result = await (template | model.with_structured_output(Starters)).ainvoke(
            {"overview": _summary(overview)}, config=config
        )
        starters = result if isinstance(result, Starters) else Starters.model_validate(result)
        questions = [q.strip() for q in starters.questions if q.strip()]
        if MIN_QUESTIONS <= len(questions) <= MAX_QUESTIONS:
            return questions, "llm"
    except Exception:
        logger.info("starter question generation failed; using templates", exc_info=True)
    return template_questions(overview), "template"
