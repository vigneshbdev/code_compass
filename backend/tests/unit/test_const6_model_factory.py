"""Constitution VI: one model factory, models chosen by config (task T011).

No network: litellm calls are monkeypatched.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import litellm
import pytest
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel

from codecompass.config import Settings
from codecompass.llm.factory import LiteLLMModelFactory


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    env = {
        "DATABASE_URL": "postgresql+psycopg://u:p@db:5432/codecompass",
        "LLM_MODEL": "provider/answer-model",
        "LLM_FAST_MODEL": "provider/fast-model",
        "LLM_JUDGE_MODEL": "provider/judge-model",
        "EMBEDDING_MODEL": "provider/embed-model",
        "EMBEDDING_DIM": "8",
        "GEMINI_API_KEY": "test-key",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)


@pytest.mark.parametrize(
    ("role", "expected"),
    [
        ("answer", "provider/answer-model"),
        ("fast", "provider/fast-model"),
        ("judge", "provider/judge-model"),
    ],
)
def test_const6_chat_role_maps_to_configured_model(
    settings: Settings, role: str, expected: str
) -> None:
    model = LiteLLMModelFactory(settings).chat(role)  # type: ignore[arg-type]  # parametrized str
    assert isinstance(model, BaseChatModel)
    assert model.model == expected  # type: ignore[attr-defined]


async def test_const6_embeddings_use_configured_model_and_dim(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_aembedding(**kwargs: Any) -> SimpleNamespace:
        calls.append(kwargs)  # LiteLLM returns an EmbeddingResponse with a `.data` list
        return SimpleNamespace(data=[{"embedding": [0.1] * 8} for _ in kwargs["input"]])

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)
    emb = LiteLLMModelFactory(settings).embeddings()
    assert isinstance(emb, Embeddings)
    vectors = await emb.aembed_documents(["a", "b"])
    assert len(vectors) == 2 and len(vectors[0]) == 8
    assert calls[0]["model"] == "provider/embed-model"
    assert calls[0]["dimensions"] == 8


class _AuthError(Exception):
    pass


class _ConnError(Exception):
    pass


@pytest.mark.parametrize(
    ("raised", "expected"),
    [(None, "ok"), (_AuthError, "invalid"), (_ConnError, "unreachable")],
)
async def test_const6_check_maps_provider_errors(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    raised: type[Exception] | None,
    expected: str,
) -> None:
    monkeypatch.setattr(
        litellm,
        "validate_environment",
        lambda model: {"keys_in_environment": True, "missing_keys": []},
    )
    monkeypatch.setattr(litellm, "AuthenticationError", _AuthError)
    monkeypatch.setattr(litellm, "APIConnectionError", _ConnError)

    async def fake_aembedding(**kwargs: Any) -> dict[str, Any]:
        if raised is not None:
            raise raised("boom")
        return {"data": [{"embedding": [0.0] * 8}]}

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)
    assert await LiteLLMModelFactory(settings).check() == expected


async def test_const6_check_reports_missing_key(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        litellm,
        "validate_environment",
        lambda model: {"keys_in_environment": False, "missing_keys": ["GEMINI_API_KEY"]},
    )
    assert await LiteLLMModelFactory(settings).check() == "missing"


async def test_const6_check_reports_empty_key_as_missing(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GEMINI_API_KEY=` (empty) passes litellm's env check but fails the call (NFR-007)."""
    monkeypatch.setattr(
        litellm,
        "validate_environment",
        lambda model: {"keys_in_environment": True, "missing_keys": []},
    )
    monkeypatch.setattr(litellm, "APIConnectionError", _ConnError)

    async def fake_aembedding(**kwargs: Any) -> Any:
        raise _ConnError("litellm.APIConnectionError: Missing Gemini API key. Set GEMINI_API_KEY.")

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)
    assert await LiteLLMModelFactory(settings).check() == "missing"
