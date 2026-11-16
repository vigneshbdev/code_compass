# Research: Code Documentation Assistant (Phase 0)

**Feature**: `001-code-assistant` | **Date**: 2026-11-16 (rev. 2) | **Plan**: [plan.md](plan.md)

Each decision records what was chosen, why, and what was rejected.

**Rev. 2 (author direction, 2026-11-16):** build to an enterprise standard and use the
author's toolkit (LangChain, NeMo Guardrails, Langfuse, LiteLLM) wherever it fits.
Decisions R3, R5, R6, R9, R10, R11 and R12 changed as a result. Postgres replaces SQLite
because self-hosted Langfuse needs it anyway.

---

## R1. Overall shape: one app service + platform services in Compose

- **Decision**: one application service (FastAPI) serves the API and the built React SPA. It
  runs next to standard platform services in `docker-compose.yml`:
  - **Postgres 16 + pgvector**: app data and vectors, plus the Langfuse metadata database;
  - **Langfuse v4**: `langfuse-web`, `langfuse-worker`, ClickHouse, Redis and MinIO, as in
    Langfuse's reference compose file.

  `docker compose up` still starts everything with one command (NFR-003). Every service has a
  healthcheck, and `app` waits for Postgres with `depends_on: condition: service_healthy`.
  Langfuse is created headless through its `LANGFUSE_INIT_*` env vars (org, project, API keys
  and admin user), so the reviewer never has to sign up or click through a setup screen.
- **Rationale**: our own code stays one process (Constitution II); the extra containers are
  off-the-shelf platform components. Serving the SPA from FastAPI means one origin and no
  CORS.
- **Risk**: SC-001 (< 5 min). The Langfuse images are large on first pull. **Mitigation**:
  pinned image tags, healthchecks, a measured cold-start time in the README, and the app works
  even if Langfuse is down (tracing fails open; see R10).
- **Alternatives**: Langfuse Cloud (needs a signup per reviewer, and data leaves the machine);
  separate nginx for the SPA (no requirement needs it).

## R2. Backend language and framework

- **Decision**: Python 3.12, FastAPI, Uvicorn, Pydantic v2, `pydantic-settings`.
  SQLAlchemy 2 (async, psycopg 3) + Alembic migrations.
- **Rationale**: the RAG ecosystem (LangChain, NeMo, Langfuse SDK, RAGAS) is Python-first.
  SQLAlchemy and Alembic are the standard choice for schema evolution in an enterprise
  codebase. Typed models satisfy VIII.
- **Alternatives**: raw SQL with no migrations (fine for a demo, weak for production
  upgrades); Node (the RAG and guardrail tooling is weaker there).

## R3. LLM gateway and provider abstraction (Constitution VI, NFR-005)

- **Decision**: **LiteLLM** is the provider layer, reached through **LangChain** interfaces:
  - chat: `ChatLiteLLM` (`langchain-litellm`);
  - embeddings: a LangChain `Embeddings` backed by `litellm.embedding` (from
    `langchain-litellm` if it ships one, otherwise a ~30-line adapter).

  `llm/factory.py` is the **only** place models are built, from env: `LLM_MODEL` (answers),
  `LLM_FAST_MODEL` (query rewrite, NeMo self-checks, starter questions), `LLM_JUDGE_MODEL`
  (eval), `EMBEDDING_MODEL`, `EMBEDDING_DIM`. Defaults are the current Gemini Flash,
  Flash-Lite and Gemini embedding models, written only in `.env.example`; check the exact IDs
  when implementing. NeMo Guardrails and RAGAS receive the same LangChain model objects, so
  the whole stack swaps provider with one config change.
- **Rationale**: LiteLLM handles provider portability, retries with backoff (free-tier rate
  limits) and cost data. LangChain interfaces are the common currency that NeMo, Langfuse's
  callback handler and RAGAS all accept.
- **Option, not in v1**: run LiteLLM as a **proxy** service (virtual keys, budgets, fallbacks,
  central spend tracking). Listed under productionisation; ⚑ the author can pull it in.
- **Alternatives**: vendor SDKs directly (breaks VI).

## R4. Chunking (NFR-002, FR-015)

- **Decision**: structure-aware chunking with **tree-sitter** for Python, JavaScript and
  TypeScript/TSX:
  - one chunk per top-level function/class, including its decorators and leading
    comments/docstring;
  - classes longer than the max chunk size are split per method, and each method chunk gets
    a class-signature header line;
  - leftover top-level code goes into "module" chunks;
  - an oversized single node is split by lines (~120 lines, 15-line overlap).

  Other text files use a generic splitter: Markdown splits by heading, everything else uses
  60-line windows with a 10-line overlap. Chunkers produce LangChain `Document`s with metadata
  `path`, `start_line`, `end_line`, `language`, `kind`, `symbol`, so they plug straight into
  the LangChain retrieval stack. The embedded text starts with a short header (path, symbol,
  enclosing class).
- **Why not LangChain's splitters**: `RecursiveCharacterTextSplitter.from_language` and
  `LanguageParser` do not keep exact line spans, and FR-011/FR-012 need them. The output type
  is still LangChain's, so this is not an extra abstraction.

## R5. Storage: Postgres 16 + pgvector + full-text search

- **Decision**: one Postgres instance (image `pgvector/pgvector`) with two databases:
  `codecompass` (app) and `langfuse` (Langfuse metadata). The app database holds codebases,
  ingestions, files (redacted), chunks with a `vector(EMBEDDING_DIM)` column and a
  `tsvector` column, conversations and messages.
  - **Vector search**: cosine distance (`<=>`), filtered by `ingestion_id`. At ≤ tens of
    thousands of chunks per codebase, an exact scan behind a btree filter is fast and exact.
    An HNSW index (with pgvector iterative scan) gets added only if measurements call for it.
  - **Embedding model per ingestion** (analysis U1, author-approved 2026-11-16): each ingestion
    records `embedding_model` and `embedding_dim`. A codebase indexed with a different model is
    reported `reingest_required`, and chat on it is refused, so switching provider never
    silently mixes vector spaces. Changing the dimension also needs a new migration.
  - **Lexical search**: `tsvector` built with the `simple` configuration over the chunk text
    plus an identifier-split field we generate (`parse_config` → `parse_config parse config`;
    `getUserById` → `getUserById get user by id`), ranked with `ts_rank_cd`. GIN index.
- **Rationale**: transactions cover vectors, lexical index and metadata together, which
  makes FR-005 / scenario 1.3 ("nothing partially indexed") and the restart edge case
  straightforward (R14). Postgres + pgvector is a well-understood production choice and maps
  directly onto managed services (Cloud SQL / AlloyDB / RDS / Azure Flexible Server). It is
  already required by Langfuse, so it adds no new component.
- **Alternatives**: SQLite + sqlite-vec (rev. 1: lighter, but less standard, and Postgres is
  present anyway); `langchain-postgres` `PGVector` store (its own fixed schema cannot do our
  atomic per-ingestion swap or the symbol column, so we write custom LangChain retrievers over
  our own tables instead, see R6); Qdrant/Chroma (a second datastore with no shared
  transactions).

## R6. Retrieval: LangChain hybrid retriever (FR-014, FR-015, SC-002)

- **Decision**: LCEL pipeline, per question:
  1. **History-aware rewrite**: an LCEL step with the fast model turns the question and the
     last turns into a `standalone_question` and `identifiers` (structured output), the same
     pattern as LangChain's history-aware retriever (FR-014). Identifiers are also extracted
     by regex (backticks, `snake_case`, `camelCase`, `dotted.names`) so FR-015 never depends
     on the LLM.
  2. **Three custom `BaseRetriever`s** over our Postgres tables, scoped to the codebase's
     active ingestion (FR-006):
     - `VectorRetriever`: top 20;
     - `LexicalRetriever`: top 20 full-text matches;
     - `SymbolRetriever`: exact, then case-insensitive, match on `symbol` / `symbol_leaf`.
  3. **Fusion**: Reciprocal Rank Fusion (k = 60) over vector and lexical, written in-house in
     `retrieval/hybrid.py` (~20 lines). `EnsembleRetriever` moved to the legacy
     `langchain-classic` package in LangChain 1.x, and our own version writes each chunk's
     per-retriever rank and fused score into the trace (author decision 2026-11-16). Symbol hits
     are pinned to the top, which makes scenario 2.5 deterministic.
  4. **Context packing**: overlapping spans in the same file are merged, then the result is
     cut to a budget (default 8 chunks / ~6k tokens, configurable).

  Retriever runs appear as spans in Langfuse automatically through the callback handler.
  Ranks and scores go into document metadata so they show in the trace.
- **Alternatives**: vector only (fails FR-015); a reranker (cross-encoder, or Cohere/Vertex
  rerank via LangChain) is ⚑ **an optional v1.1 step**, turned on by config if eval hit-rate
  is below 80%. Left out by default to protect NFR-001.

## R7. Grounding, citations and "not found" (FR-011, FR-013, SC-003, Constitution III)

- **Decision** (unchanged in substance):
  - Chunks go into the prompt as `<chunk id path lines>…</chunk>`.
  - The prompt requires `[path:start-end]` citations inside the provided chunks and the exact
    sentence `I couldn't find this in the codebase.` when the context does not support an
    answer.
  - **Pre-check**: if no lexical or symbol hits *and* the best vector similarity is below
    `RETRIEVAL_MIN_SCORE`, return the not-found answer without calling the LLM.
  - **Post-check**: parse citations, validate path and range against the packed chunks, drop
    invalid ones and record counts as Langfuse scores. A claim-making answer left with no valid
    citation is stored and shown with status `unverified` and a visible badge (analysis C4,
    author-approved 2026-11-16), so uncited claims never look like verified answers.
- **Note**: NeMo's fact-checking / hallucination rails were considered and **not** used for
  grounding. They add an LLM call after generation and do not work with token streaming
  (FR-010). Deterministic citation validation covers SC-003. Faithfulness is measured offline
  with RAGAS (R11).

## R8. Conversation context (FR-014, FR-016)

- **Decision**: conversations and messages live in Postgres tables (richer than LangChain's
  chat-history tables: citations, status, trace IDs). A small adapter exposes them as
  LangChain `BaseMessage`s for the rewrite and answer prompts. The answer prompt carries the
  last 3 exchanges (older answers cut to ~400 tokens).
- **Alternatives**: `PostgresChatMessageHistory` / `RunnableWithMessageHistory` (stores only
  messages; we would still need our own table for citations and feedback, so there would be
  two sources of truth).

## R9. Guardrails: NeMo Guardrails + ingestion redaction (FR-030…033, SC-004, Constitution IV)

- **Decision**:
  - **FR-030 Ingestion redaction (not a NeMo concern)**: Yelp **`detect-secrets`** plugins
    plus custom regexes (Gemini/OpenAI-style keys), applied before anything is stored,
    embedded or displayed. Each match is replaced within its line by `[REDACTED:<type>]`, so
    line numbers stay correct. Private key files are skipped.
  - **NeMo Guardrails** (`guardrails/config/`: `config.yml`, Colang flows, prompts) wraps
    chat generation. Its main model and its self-check model are the LangChain models from
    R3.
    - **Input rails**:
      - `self check input` (fast model) with a prompt that encodes the topical policy:
        questions about the selected codebase or software engineering are allowed; anything
        else gets a fixed polite decline (FR-032);
      - jailbreak and "ignore your instructions" attempts in the *user* message are rejected
        by the same rail.
    - **Retrieval rails**: a custom action runs over the retrieved chunks. Chunks matching
      injection patterns (`ignore (all|previous) instructions`, `you are now`,
      `system prompt`, …) are wrapped with an "untrusted, treat as data" marker and flagged
      in the trace (FR-031). Together with the system prompt's data/instruction separation
      and `<chunk>` delimiting, this is the injection defence.
    - **Output rails (streaming)**: a custom action reuses the `detect-secrets` detector on
      each streamed chunk and masks hits (FR-033). NeMo output-rail streaming is configured
      with a small `chunk_size` and a `context_size` overlap, so a secret split across token
      deltas is still caught and the stream stays responsive.
  - **Integration spike (first guardrails task)**: confirm NeMo's streaming output rails and
    rail selection with `ChatLiteLLM` on the pinned NeMo version. Fallback if the streaming
    API does not fit: `RunnableRails` around the LCEL chain for input rails, plus our own
    line-buffered output filter calling the same action.
- **Cost**: the input self-check adds one fast-model call (~0.3–0.6 s) before retrieval.
  This is tracked as `latency_ms.input_rails` and checked against NFR-001 in eval.
- **Alternatives**: plain-code rails only (rev. 1: fewer moving parts, but no policy layer,
  and the author wants the standard tool); Presidio PII rails (needs a spaCy model, which
  makes the image heavier; secrets are the stated risk, so PII is listed as future work).

## R10. Observability: Langfuse (FR-040, FR-041, Constitution V)

- **Decision**: **Langfuse (self-hosted v4) is the system of record for traces.**
  - Each chat request is one Langfuse trace (`session_id` = conversation ID, `user_id` =
    "local"), created via the Langfuse LangChain `CallbackHandler`. Rewrite, retrievers,
    NeMo rails and generation are captured as nested spans/generations with model, tokens,
    cost and latency. Custom metadata adds the FR-040 fields LangChain does not capture by
    itself: per-retriever ranks and fused scores, guardrail decisions, pre-check result,
    citation validity counts.
  - **Prompt management**: prompts live in git (`backend/src/codecompass/prompts/*.yaml`, the
    reviewable source of truth) and are synced to Langfuse at startup with version labels.
    Generations are linked to the prompt version, so changes can be compared in Langfuse.
  - **Feedback (FR-041)**: thumbs up/down are saved on the message (for the UI) and sent as a
    Langfuse score on the trace.
  - **UI**: each answer has an "Open in Langfuse" link to its trace. The in-app trace drawer
    was cut in the scope revision of 2026-11-16, because Langfuse is the better trace UI and
    showing it is the point.
  - **Fail-open**: if Langfuse is unreachable, chat still works; the SDK drops or buffers
    events, and the drawer shows "trace unavailable". The message keeps a usage summary
    (tokens, cost, first-token latency) so core numbers are never lost.
  - Structured JSON logs carry the trace ID for correlation.
- **Alternatives**: a local trace table (rev. 1: lighter, but no dashboards, datasets, prompt
  versioning or experiment comparison); OpenTelemetry + Jaeger (LLM-specific fields would be
  custom).

## R11. Evaluation: Langfuse Datasets + RAGAS (FR-042, SC-002, SC-003)

- **Decision**:
  - The **source of truth** is `eval/datasets/fastapi-template-v1.yaml` in git (pinned commit,
    author-verified `expected_files`).
  - `make eval` does the following:
    1. ingests the pinned commit if it isn't already ingested;
    2. upserts the items into a **Langfuse Dataset** named after the file version;
    3. runs every item through the **same** chain as a Langfuse dataset run linked to its
       traces;
    4. scores each item:
       - retrieval **hit-rate** and **citation validity** (custom);
       - **RAGAS** `faithfulness`, `context_precision` and `context_recall`, using
         `LLM_JUDGE_MODEL` through the LangChain wrapper;
       - not-found and off-topic accuracy;
    5. pushes all scores to Langfuse and writes `eval/reports/<dataset>-<ts>.{json,md}`.

    Runs can then be compared side by side in Langfuse.
- **Packaging**: RAGAS lives in the `eval` dependency group and the `eval` compose service, not in
  the app image (author decision 2026-11-16), keeping the app build within the setup budget.
- **Alternatives**: a custom LLM judge only (rev. 1); RAGAS's names and definitions are the
  recognised industry metrics.

## R12. LangChain: where and where not

- **Decision**: LangChain (≥ 1.0) is the orchestration layer:
  - LCEL chain for rewrite → retrieve → pack → generate;
  - `Document` and `BaseRetriever` (fusion is our own code, see R6);
  - chat and embedding model interfaces (via `langchain-litellm`);
  - prompt templates;
  - the Langfuse callback.

  It is **not** used for code splitting (R4), the PGVector store (R5) or chat-history storage
  (R8), because each of those would lose information our requirements need. LangChain imports
  stay inside `chat/`, `retrieval/`, `llm/` and `eval/`, so the domain code (ingestion,
  chunking, overview, storage) is plain Python and easy to test.
- **Agents**: no LangChain/LangGraph agent loop in v1. The pipeline is deterministic, and an
  agent would add latency and unpredictability to NFR-001 and SC-003. A tool-using agent for
  multi-hop questions ("trace this request end to end") is listed as future work.

## R13. Ingestion sources and safety (FR-001…005, edge cases)

Unchanged from rev. 1:
- **GitHub**: GitHub REST metadata check (size estimate; 404 → private/misspelt; 403/429 →
  rate-limited), then a streamed tarball via `httpx` with a byte cap. The API base URL comes
  from config, and `GITHUB_TOKEN` is optional.
- **Zip/tar**: reject absolute and `..` paths, skip symlinks, cap uncompressed size and entry
  count.
- **Filtering**: `.gitignore` (`pathspec`), deny list (`node_modules`, `dist`, `vendor`,
  `.venv`, lockfiles, `*.min.js`, …), binary detection, a 512 KB per-file cap, UTF-8 only.
  Every skip records a reason.
- **Limits**: more than 5,000 indexable files or 50 MB of indexable content → reject before
  embedding.

## R14. Ingestion execution, progress, atomicity

- **Decision**: an in-process `asyncio` task (CPU-bound parsing in a thread pool) behind a
  global semaphore (one ingestion at a time, the rest `queued`). Progress is kept on the
  ingestion row, and the UI polls every second. Embeddings are batched with LiteLLM backoff.
  **Atomic swap**: rows are written under a new `ingestion_id`, then one transaction updates
  `codebase.active_ingestion_id` and deletes the previous ingestion's rows. Startup recovery
  marks interrupted work `failed` and cleans up its rows. Each ingestion is also traced in
  Langfuse (embedding cost and duration).
- **Uploads are kept** (added during US1) at `DATA_DIR/uploads/<codebase-id>.zip` on the app's
  data volume, so a zip codebase can be re-ingested or retried. They are deleted with the
  codebase.
- **No LLM key, no ingestion** (NFR-007, added during US1): submit and re-ingest return
  `503 llm_unavailable` while the startup LLM check is not `ok`. An embedding failure mid-run
  fails the ingestion with the same code and a clear message.
- **Alternatives**: Celery/RQ on the Redis that Langfuse brings. **Rejected**: that Redis
  belongs to Langfuse, and a worker fleet is not needed for single-user ingestion. Listed
  under productionisation (Cloud Tasks/SQS + workers).

## R15. Re-ingestion and stale citations

Re-ingest swaps atomically and conversations survive; citations open the current file. Each
citation stores a `content_hash`. Flagging "code changed since this answer" was cut in the scope
revision of 2026-11-16 and is listed as future work; the stored hash means it needs no migration.

## R16. Startup checks (NFR-007)

- **Decision**: at startup the app checks the provider key with a 1-token embedding, checks
  the database, and checks that Langfuse is reachable. `GET /api/health` reports each one.
  A missing or invalid LLM key gives a blocking UI banner with the README link. Langfuse down
  is a non-blocking warning. The process never crash-loops.

## R17. Codebase overview (FR-020, FR-021)

Trimmed in the scope revision of 2026-11-16:
- language breakdown (files and lines per language);
- dependencies (`pyproject.toml`, `requirements*.txt`, `package.json`), read from redacted content;
- 3–5 starter questions from the fast model (traced in Langfuse), with a template fallback.

Cut (future work): top-level structure, entry-point heuristics, API route detection.

## R18. Frontend

- **Decision**: React 18 + TypeScript + Vite, Tailwind CSS (+ dark mode),
  **TanStack Query** for server state (polling, cache invalidation across codebases and
  conversations; added in rev. 2 as the enterprise-standard choice over hand-rolled hooks),
  `react-markdown` + `remark-gfm`, `prism-react-renderer` for the code viewer. Streaming
  uses `fetch` + SSE parsing. Keyboard: `/` focuses input, `Esc` closes the drawer,
  citations are buttons.

## R19. Testing and tooling (Constitution VII, Quality Gate 4)

- **Decision**:
  - **Unit tests** (no I/O): chunking, filters, redaction, injection action, output-rail
    action, fusion and symbol pinning, citation validation, overview extractors, eval
    metrics.
  - **Integration tests**: FastAPI via `httpx.ASGITransport` against a real Postgres +
    pgvector started by **testcontainers**. LLM stand-ins: LangChain fake chat models
    (`FakeListChatModel` / a scripted streaming fake) and a deterministic hashed-embedding
    fake, injected through `llm/factory.py`. NeMo runs with the same fakes. Langfuse is
    disabled in tests (no-op handler) except one test using a mock HTTP server to assert the
    trace payload and FR-040 fields.
  - **Opt-in** `@pytest.mark.live` smoke tests against the real provider and a live Langfuse.
  - **Frontend**: Vitest + Testing Library.
  - **Lint**: ruff, mypy --strict, eslint, `tsc --noEmit`.
  - **Tooling**: `uv`, npm.
  - `make test` needs Docker (testcontainers) but no API key or internet beyond image pulls.

## R20. Configuration and secrets for the stack

- **Decision**: one `.env.example` holds every setting: app, Postgres, and Langfuse
  `LANGFUSE_INIT_*` plus `NEXTAUTH_SECRET`/`SALT`/`ENCRYPTION_KEY`. Infrastructure secrets
  are clearly marked **dev-only placeholders**, and `make init-env` generates random values
  for them. Nothing secret is in code or committed `.env` files (CLAUDE.md: no hard-coded
  keys). Productionisation maps these to Secret Manager / Key Vault.
