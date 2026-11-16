"""Settings for unit tests that need no database (US1 tests)."""

from __future__ import annotations

from typing import Any

from codecompass.config import Settings

UNIT_ENV: dict[str, Any] = {
    "database_url": "postgresql+psycopg://unused:unused@127.0.0.1:1/unused",
    "llm_model": "fake/answer",
    "llm_fast_model": "fake/fast",
    "llm_judge_model": "fake/judge",
    "embedding_model": "fake/embed",
    "embedding_dim": 64,
    "langfuse_enabled": False,
}


def make_settings(**overrides: Any) -> Settings:
    return Settings(_env_file=None, **{**UNIT_ENV, **overrides})
