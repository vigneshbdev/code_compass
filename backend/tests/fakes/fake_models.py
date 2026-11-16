"""Offline stand-in for the ModelFactory contract (task T020, contracts/llm-provider.md).

- Chat models answer from a per-role script (strings, or dicts for structured output),
  stream token by token, can raise mid-stream, and record every prompt they receive.
- Embeddings are a deterministic hashed bag-of-words, L2-normalised, so texts that share
  words are close. Good enough to exercise retrieval without a provider.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections import deque
from collections.abc import AsyncIterator, Iterator, Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda
from pydantic import BaseModel, ConfigDict, Field

from codecompass.llm.factory import ChatRole, CheckResult

DEFAULT_REPLY = "OK"
TOKEN = re.compile(r"\S+\s*|\s+")
WORD = re.compile(r"[a-z0-9]+")


class ScriptedStreamError(RuntimeError):
    """Raised by a fake model mid-stream to simulate a provider failure."""


class FakeChatModel(BaseChatModel):
    """Answers from a script. Each call consumes the next scripted item."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    role: str = "answer"
    default_reply: str = DEFAULT_REPLY
    script: deque[Any] = Field(default_factory=deque)
    prompts: list[list[BaseMessage]] = Field(default_factory=list)
    fail_after_tokens: int | None = None  # raise ScriptedStreamError after N streamed tokens

    @property
    def _llm_type(self) -> str:
        return "fake-scripted"

    def _next(self) -> Any:
        return self.script.popleft() if self.script else self.default_reply

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.prompts.append(list(messages))
        reply = self._next()
        text = reply if isinstance(reply, str) else str(reply)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        self.prompts.append(list(messages))
        reply = self._next()
        for i, token in enumerate(TOKEN.findall(str(reply))):
            if self.fail_after_tokens is not None and i >= self.fail_after_tokens:
                raise ScriptedStreamError("provider failed mid-stream")
            yield ChatGenerationChunk(message=AIMessageChunk(content=token))

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        for chunk in self._stream(messages, stop, None, **kwargs):
            yield chunk

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Runnable[Any, Any]:
        def _invoke(value: Any) -> Any:
            messages = value.to_messages() if hasattr(value, "to_messages") else value
            if isinstance(messages, Sequence) and not isinstance(messages, str):
                self.prompts.append(list(messages))
            reply = self._next()
            if isinstance(schema, type) and issubclass(schema, BaseModel):
                return schema.model_validate(reply)
            return reply

        return RunnableLambda(_invoke)


class HashEmbeddings(Embeddings):
    def __init__(self, dim: int) -> None:
        self.dim = dim
        self.calls = 0
        self.gate: asyncio.Event | None = None  # when set, aembed_documents waits for it

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        for word in WORD.findall(text.lower()):
            digest = hashlib.md5(word.encode(), usedforsecurity=False).digest()
            vec[int.from_bytes(digest[:4], "big") % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            vec[0] = 1.0
            return vec
        return [v / norm for v in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [self._vector(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)

    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        if self.gate is not None:
            await self.gate.wait()
        return self.embed_documents(texts)

    async def aembed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FakeModelFactory:
    """Implements the ModelFactory protocol for tests."""

    def __init__(
        self,
        *,
        dim: int = 768,
        check_result: CheckResult = "ok",
        scripts: dict[str, list[Any]] | None = None,
    ) -> None:
        self.check_result = check_result
        self.embedder = HashEmbeddings(dim)
        # The fast model answers NeMo's "should this be blocked?" check: default "No" (allow).
        self.models: dict[str, FakeChatModel] = {
            role: FakeChatModel(
                role=role,
                script=deque((scripts or {}).get(role, [])),
                default_reply="No" if role == "fast" else DEFAULT_REPLY,
            )
            for role in ("answer", "fast", "judge")
        }

    def script(self, role: str, *replies: Any) -> None:
        self.models[role].script.extend(replies)

    def chat(self, role: ChatRole, *, streaming: bool = False) -> FakeChatModel:
        return self.models[role]

    def embeddings(self) -> HashEmbeddings:
        return self.embedder

    async def check(self) -> CheckResult:
        return self.check_result

    def prompts(self, role: str) -> list[list[BaseMessage]]:
        return self.models[role].prompts
