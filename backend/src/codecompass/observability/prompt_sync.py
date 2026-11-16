"""Prompts live in git and are versioned in Langfuse (FR-043, research R10, task T024).

Git is the source of truth. At startup each prompt whose content hash changed gets a new
Langfuse version labelled `production`. Traces record `Prompt.version`: the Langfuse version
number when synced, or `local-<hash>` when Langfuse is unavailable.

Syncing fails open (Langfuse down → local versions). Loading does not: a prompt file whose
declared `variables` don't match its template stops startup, because that is a developer error
that would otherwise surface as a broken chat request.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
LABEL = "production"
ROLE_TO_LANGCHAIN = {"system": "system", "user": "human", "assistant": "ai"}


@dataclass
class Prompt:
    name: str
    messages: list[dict[str, str]]
    template: ChatPromptTemplate
    content_hash: str
    version: str


def _hash(messages: list[dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()


def _load(path: Path) -> Prompt:
    data = yaml.safe_load(path.read_text())
    messages: list[dict[str, str]] = [
        {"role": str(m["role"]), "content": str(m["content"])} for m in data["messages"]
    ]
    template = ChatPromptTemplate.from_messages(
        [(ROLE_TO_LANGCHAIN[m["role"]], m["content"]) for m in messages]
    )
    declared = set(data.get("variables") or [])
    if declared != set(template.input_variables):
        raise ValueError(
            f"{path.name}: declared variables {sorted(declared)} do not match the template's "
            f"{sorted(template.input_variables)}"
        )
    content_hash = _hash(messages)
    return Prompt(
        name=str(data["name"]),
        messages=messages,
        template=template,
        content_hash=content_hash,
        version=f"local-{content_hash[:12]}",
    )


class PromptRegistry:
    def __init__(self, directory: Path = PROMPTS_DIR) -> None:
        self._prompts: dict[str, Prompt] = {}
        for path in sorted(directory.glob("*.yaml")):
            prompt = _load(path)
            self._prompts[prompt.name] = prompt

    def get(self, name: str) -> Prompt:
        return self._prompts[name]

    def names(self) -> list[str]:
        return list(self._prompts)

    def sync(self, langfuse: Any | None) -> None:
        """Push changed prompts to Langfuse. Never raises: falls back to local versions."""
        if langfuse is None:
            return
        for prompt in self._prompts.values():
            try:
                prompt.version = self._sync_one(langfuse, prompt)
            except Exception:
                logger.warning(
                    "prompt sync failed; using local version",
                    extra={"data": {"prompt": prompt.name}},
                )

    @staticmethod
    def _sync_one(langfuse: Any, prompt: Prompt) -> str:
        try:
            current = langfuse.get_prompt(prompt.name, label=LABEL, type="chat")
        except (ConnectionError, OSError):
            raise
        except Exception:
            current = None  # prompt does not exist yet
        if (
            current is not None
            and (current.config or {}).get("content_hash") == prompt.content_hash
        ):
            return str(current.version)
        created = langfuse.create_prompt(
            name=prompt.name,
            prompt=prompt.messages,
            labels=[LABEL],
            type="chat",
            config={"content_hash": prompt.content_hash},
            commit_message=f"sync from git ({prompt.content_hash[:12]})",
        )
        return str(created.version)
