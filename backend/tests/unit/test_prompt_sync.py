"""FR-043: prompts are versioned in git; traces can record the prompt version (task T024)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from codecompass.observability.prompt_sync import PromptRegistry

PROMPT_YAML = """\
name: greet
description: test prompt
variables: [who]
messages:
  - role: system
    content: You are terse.
  - role: user
    content: Say hello to {who}.
"""


@pytest.fixture
def prompt_dir(tmp_path: Path) -> Path:
    (tmp_path / "greet.yaml").write_text(PROMPT_YAML)
    return tmp_path


class FakeLangfuse:
    def __init__(self, current_hash: str | None = None, fail: bool = False) -> None:
        self.current_hash = current_hash
        self.fail = fail
        self.created: list[dict[str, Any]] = []

    def get_prompt(self, name: str, label: str = "production", **_: Any) -> Any:
        if self.fail:
            raise ConnectionError("langfuse down")
        if self.current_hash is None:
            raise LookupError("not found")
        return SimpleNamespace(version=7, config={"content_hash": self.current_hash})

    def create_prompt(self, **kwargs: Any) -> Any:
        if self.fail:
            raise ConnectionError("langfuse down")
        self.created.append(kwargs)
        return SimpleNamespace(version=8)


def test_fr043_loads_yaml_into_chat_template(prompt_dir: Path) -> None:
    registry = PromptRegistry(prompt_dir)
    prompt = registry.get("greet")
    messages = prompt.template.format_messages(who="Ada")
    assert [m.type for m in messages] == ["system", "human"]
    assert messages[1].content == "Say hello to Ada."


def test_fr043_local_version_is_stable_content_hash(prompt_dir: Path, tmp_path: Path) -> None:
    first = PromptRegistry(prompt_dir).get("greet").version
    assert first.startswith("local-")
    assert PromptRegistry(prompt_dir).get("greet").version == first
    (prompt_dir / "greet.yaml").write_text(PROMPT_YAML.replace("terse", "verbose"))
    assert PromptRegistry(prompt_dir).get("greet").version != first


def test_fr043_sync_creates_new_version_when_content_changed(prompt_dir: Path) -> None:
    registry = PromptRegistry(prompt_dir)
    lf = FakeLangfuse(current_hash="something-else")
    registry.sync(lf)
    assert len(lf.created) == 1
    created = lf.created[0]
    assert created["name"] == "greet"
    assert created["labels"] == ["production"]
    assert created["type"] == "chat"
    assert created["config"]["content_hash"] == registry.get("greet").content_hash
    assert registry.get("greet").version == "8"


def test_fr043_sync_skips_unchanged_prompt(prompt_dir: Path) -> None:
    registry = PromptRegistry(prompt_dir)
    lf = FakeLangfuse(current_hash=registry.get("greet").content_hash)
    registry.sync(lf)
    assert lf.created == []
    assert registry.get("greet").version == "7"


def test_fr043_sync_falls_back_to_local_when_langfuse_down(prompt_dir: Path) -> None:
    registry = PromptRegistry(prompt_dir)
    local = registry.get("greet").version
    registry.sync(FakeLangfuse(fail=True))
    assert registry.get("greet").version == local


def test_fr043_unknown_prompt_raises(prompt_dir: Path) -> None:
    with pytest.raises(KeyError):
        PromptRegistry(prompt_dir).get("missing")


def test_fr043_declared_variables_must_match_template(prompt_dir: Path) -> None:
    (prompt_dir / "greet.yaml").write_text(
        PROMPT_YAML.replace("variables: [who]", "variables: [whom]")
    )
    with pytest.raises(ValueError, match="do not match"):
        PromptRegistry(prompt_dir)
