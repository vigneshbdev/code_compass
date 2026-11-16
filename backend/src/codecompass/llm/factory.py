"""The single place models are built (Constitution VI, contracts/llm-provider.md, task T022).

Every consumer (the chat chain, NeMo Guardrails, RAGAS, ingestion) receives LangChain
`BaseChatModel` / `Embeddings` objects from here, so changing provider is a config change.
"""

from __future__ import annotations

import logging
import re
from typing import Literal, Protocol

import litellm
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_litellm import ChatLiteLLM, LiteLLMEmbeddings

from codecompass.config import Settings

logger = logging.getLogger(__name__)

ChatRole = Literal["answer", "fast", "judge"]
CheckResult = Literal["ok", "missing", "invalid", "unreachable"]

MISSING_KEY = re.compile(r"missing .{0,40}api key|api key .{0,20}not (set|found)", re.IGNORECASE)
MAX_RETRIES = 3  # LiteLLM retries 429/5xx with backoff (discovery risk: free-tier rate limits)


class ModelFactory(Protocol):
    def chat(self, role: ChatRole, *, streaming: bool = False) -> BaseChatModel: ...

    def embeddings(self) -> Embeddings: ...

    async def check(self) -> CheckResult: ...


class LiteLLMModelFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._models: dict[ChatRole, str] = {
            "answer": settings.llm_model,
            "fast": settings.llm_fast_model,
            "judge": settings.llm_judge_model,
        }

    def chat(self, role: ChatRole, *, streaming: bool = False) -> BaseChatModel:
        return ChatLiteLLM(
            model=self._models[role],
            streaming=streaming,
            max_retries=MAX_RETRIES,
            temperature=0,
            # Ask providers to report token usage on the final streamed chunk (FR-040).
            model_kwargs={"stream_options": {"include_usage": True}} if streaming else {},
        )

    def embeddings(self) -> Embeddings:
        return LiteLLMEmbeddings(
            model=self._settings.embedding_model,
            dimensions=self._settings.embedding_dim,
            max_retries=MAX_RETRIES,
        )

    async def check(self) -> CheckResult:
        """Cheap startup probe: key present, then a 1-token embedding (research R16)."""
        env = litellm.validate_environment(model=self._settings.embedding_model)
        if not env.get("keys_in_environment", False):
            logger.warning("LLM key missing", extra={"data": {"missing": env.get("missing_keys")}})
            return "missing"
        try:
            await litellm.aembedding(
                model=self._settings.embedding_model,
                input=["ping"],
                dimensions=self._settings.embedding_dim,
            )
        except litellm.AuthenticationError:  # type: ignore[attr-defined]
            return "invalid"
        except litellm.APIConnectionError as exc:  # type: ignore[attr-defined]
            # An empty key variable (`<PROVIDER>_API_KEY=`) passes validate_environment and
            # only fails here.
            return "missing" if MISSING_KEY.search(str(exc)) else "unreachable"
        except Exception:
            logger.exception("LLM check failed")
            return "unreachable"
        return "ok"


def cost_usd(model: str, tokens_in: int, tokens_out: int) -> float:
    """Estimated cost from LiteLLM's price table; 0.0 when the model is not priced."""
    try:
        prompt, completion = litellm.cost_per_token(
            model=model, prompt_tokens=tokens_in, completion_tokens=tokens_out
        )
        return round(float(prompt) + float(completion), 6)
    except Exception:
        return 0.0
