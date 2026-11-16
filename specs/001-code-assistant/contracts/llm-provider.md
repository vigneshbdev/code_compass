# Contract: model factory (Constitution VI, NFR-005)

An internal module boundary. It is documented because it is the single place where provider
choice happens, and because tests depend on swapping it out.

```python
# backend/src/codecompass/llm/factory.py
class ModelFactory(Protocol):
    def chat(self, role: Literal["answer", "fast", "judge"], *, streaming: bool = False) -> BaseChatModel: ...
    def embeddings(self) -> Embeddings: ...
    async def check(self) -> Literal["ok", "missing", "invalid", "unreachable"]: ...
```

- `BaseChatModel` and `Embeddings` are the **LangChain** interfaces. Everything that needs a
  model takes one of these:
  - the LCEL chat chain;
  - the NeMo Guardrails main and self-check models;
  - RAGAS judges;
  - starter-question generation;
  - ingestion embedding.
- `role` maps to `LLM_MODEL`, `LLM_FAST_MODEL` and `LLM_JUDGE_MODEL`; embeddings map to
  `EMBEDDING_MODEL` / `EMBEDDING_DIM`. No other module reads model IDs, and no literals
  appear anywhere (CLAUDE.md).
- Implementations:
  - `LiteLLMModelFactory` (production): `ChatLiteLLM` + a LiteLLM-backed `Embeddings`, with
    retries and backoff on 429/5xx. Auth or exhausted-retry failures raise
    `ProviderUnavailable`, which the API maps to `llm_unavailable` or an SSE `error`.
  - `FakeModelFactory` (tests only): scripted LangChain fake chat models (including a
    streaming fake) and deterministic hashed bag-of-words embeddings, so chunking,
    retrieval, NeMo rails and chat integration tests run offline.
- Usage, cost and latency are captured by the Langfuse LangChain callback attached to each
  run. The factory does not compute them itself.
