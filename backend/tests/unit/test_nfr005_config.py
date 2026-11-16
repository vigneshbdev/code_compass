"""NFR-005: all keys, model names and URLs come from environment variables (task T010)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from codecompass.config import Settings

SRC = Path(__file__).resolve().parents[2] / "src" / "codecompass"

REQUIRED_ENV = {
    "DATABASE_URL": "postgresql+psycopg://u:p@db:5432/codecompass",
    "LLM_MODEL": "provider/answer-model",
    "LLM_FAST_MODEL": "provider/fast-model",
    "LLM_JUDGE_MODEL": "provider/judge-model",
    "EMBEDDING_MODEL": "provider/embed-model",
    "EMBEDDING_DIM": "768",
}


def _settings(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> Settings:
    for key, value in {**REQUIRED_ENV, **overrides}.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


def test_nfr005_settings_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch, MAX_FILES="12", RETRIEVAL_MIN_SCORE="0.5", LANGFUSE_ENABLED="false")
    assert s.llm_model == "provider/answer-model"
    assert s.llm_fast_model == "provider/fast-model"
    assert s.llm_judge_model == "provider/judge-model"
    assert s.embedding_model == "provider/embed-model"
    assert s.embedding_dim == 768
    assert s.max_files == 12
    assert s.retrieval_min_score == 0.5
    assert s.langfuse_enabled is False


def test_nfr005_limit_defaults_match_spec(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch)
    assert s.max_files == 5000  # NFR-004
    assert s.max_index_bytes == 50_000_000  # NFR-004
    assert s.max_file_bytes == 524_288  # research R13


@pytest.mark.parametrize(
    "missing",
    [
        "DATABASE_URL",
        "LLM_MODEL",
        "LLM_FAST_MODEL",
        "LLM_JUDGE_MODEL",
        "EMBEDDING_MODEL",
        "EMBEDDING_DIM",
    ],
)
def test_nfr005_missing_required_setting_raises(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv(missing)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_nfr005_secrets_are_not_printed(monkeypatch: pytest.MonkeyPatch) -> None:
    s = _settings(monkeypatch, LANGFUSE_SECRET_KEY="sk-lf-x", GITHUB_TOKEN="ghp_secret")
    assert "sk-lf-x" not in repr(s)
    assert "ghp_secret" not in repr(s)


MODEL_LITERAL = re.compile(r"gemini|gpt-|claude-|text-embedding", re.IGNORECASE)
URL_LITERAL = re.compile(r"https?://")


def test_nfr005_no_hardcoded_models_or_urls_outside_config() -> None:
    offenders: list[str] = []
    for path in SRC.rglob("*.py"):
        if path.name == "config.py":
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if MODEL_LITERAL.search(line) or URL_LITERAL.search(line):
                offenders.append(f"{path.relative_to(SRC)}:{lineno}: {line.strip()}")
    assert not offenders, "hard-coded model IDs or URLs (CLAUDE.md, NFR-005):\n" + "\n".join(
        offenders
    )
