# Implementation Plan: Code Documentation Assistant

**Branch**: `001-code-assistant` | **Date**: 2026-11-16 (rev. 2) | **Spec**: [spec.md](spec.md)
**Status**: Approved by author (2026-11-16)

**Input**: Feature specification from `specs/001-code-assistant/spec.md`
**Phase 0**: [research.md](research.md) · **Phase 1**: [data-model.md](data-model.md),
[contracts/](contracts/), [quickstart.md](quickstart.md)

**Rev. 2 (author direction, 2026-11-16):** build to an enterprise standard and use LangChain,
NeMo Guardrails, Langfuse and LiteLLM wherever they fit. As a result, storage moves to
Postgres + pgvector, which Langfuse requires anyway.

## Summary

A web app. The user points it at a public GitHub repo or uploads a `.zip`, gets an instant
static overview, then chats with an assistant whose answers stream and cite exact
`path:start-end` spans.

**Technical approach:**
- **Backend**: FastAPI serving the API and the React SPA.
- **Chunking**: tree-sitter, producing LangChain `Document`s.
- **Storage**: Postgres + pgvector, with full-text search.
- **Retrieval**: a LangChain LCEL pipeline with a history-aware rewrite and hybrid search
  (vector + lexical + exact symbol, fused by `EnsembleRetriever`).
- **Models**: LiteLLM, reached through LangChain interfaces.
- **Guardrails**: NeMo Guardrails for input, retrieval and streaming output rails, plus
  `detect-secrets` redaction at ingestion.
- **Observability**: self-hosted Langfuse for traces, sessions, prompt versions, feedback
  scores and eval datasets, with RAGAS metrics.
- **Packaging**: everything starts with `docker compose up`.

## Technical Context

**Language/Version**: Python 3.12 (backend); TypeScript 5 / React 18 (frontend)
**Primary Dependencies**: FastAPI, LangChain (≥ 1.0) + `langchain-litellm`, LiteLLM, NeMo
Guardrails, Langfuse SDK, RAGAS, SQLAlchemy 2 + Alembic + psycopg 3 + pgvector, tree-sitter,
detect-secrets, pathspec, httpx. Frontend: Vite, Tailwind, TanStack Query, react-markdown,
prism-react-renderer. Each one is justified in the [Dependencies](#dependencies) table.
**Storage**: Postgres 16 + pgvector (app DB `codecompass`, plus `langfuse` DB); Langfuse also
uses ClickHouse, Redis and MinIO (its standard v4 stack)
**Testing**: pytest + pytest-asyncio; testcontainers (Postgres + pgvector); LangChain fake
models via `FakeModelFactory`; Vitest + Testing Library; ruff, mypy --strict, eslint, tsc
**Target Platform**: Docker Compose on Linux/macOS/Windows; modern desktop browsers
**Project Type**: web application (backend API + SPA in one app image) plus platform services
**Performance Goals**: first token ≤ 3 s p50 (NFR-001), including the NeMo input rail;
demo repo ingested in ~2 min on a free-tier key
**Constraints**: ≤ 5,000 indexable files / 50 MB per repo (NFR-004); all keys, model IDs
and URLs from env (NFR-005); runs on a free Gemini key; `make test` needs Docker but no API
key; chat keeps working when Langfuse is down
**Scale/Scope**: single user, no auth; a handful of codebases; tens of thousands of chunks
per codebase; 5 user stories, ~25 FRs

No NEEDS CLARIFICATION remains. The spec's clarifications plus [research.md](research.md)
resolve every item.

## Constitution Check

*GATE: must pass before Phase 0 research. Re-checked after Phase 1 design.*

| # | Principle | How this plan complies | Pre | Post |
|---|---|---|---|---|
| I | Spec is the source of truth | Every module maps to FR/NFR IDs ([map](#requirement--module-map)); tests named by ID; spec unchanged | ✅ | ✅ |
| II | Simple and solid | Our code is **one process**; ingestion is an in-process async task (no queue of our own). The Langfuse stack adds off-the-shelf containers, including a Redis queue and worker inside Langfuse. **Justified in [Complexity Tracking](#complexity-tracking)** | ⚠️ justified | ⚠️ justified |
| III | Grounded or no answer | Citations required in the prompt and validated after generation; retrieval pre-check plus the model's not-found sentence (R7) | ✅ | ✅ |
| IV | Safe by default | `detect-secrets` redaction before storage, embedding, LLM and viewer; NeMo input/retrieval/streaming-output rails; archive path guards; fixture-repo tests (R9, R13); infra secrets generated, never committed (R20) | ✅ | ✅ |
| V | Observable | A Langfuse trace per request with every FR-040 field; prompt versions; feedback scores; versioned eval set as Langfuse dataset runs + RAGAS (R10, R11) | ✅ | ✅ |
| VI | Provider-agnostic | One `ModelFactory`; LiteLLM behind LangChain interfaces shared by the chain, NeMo and RAGAS ([contracts/llm-provider.md](contracts/llm-provider.md)) | ✅ | ✅ |
| VII | Tested and reproducible | Unit tests for chunking, retrieval and guardrails; API integration tests on real Postgres (testcontainers); offline fakes; `docker compose up`; `make init-env`. Setup < 5 min excluding the one-time `docker compose pull` (constitution v1.1.0); both times measured and reported (T134) | ✅ | ✅ |
| VIII | Readable by a stranger | Modules split by RAG stage; LangChain confined to `chat/`, `retrieval/`, `llm/`, `eval/`; NeMo config in one folder; mypy strict | ✅ | ✅ |
| QG1 | Human gate | Spec and plan approved by the author on 2026-11-16 | ✅ | ✅ |
| QG2–4 | spec-reviewer, cross-review, green tests | `make test` is the command spec-reviewer runs; `scripts/cross-review.py` runs per user story | ✅ | ✅ |

**Result**: PASS, with the Principle II exception justified in Complexity Tracking.
FR-043 (prompt versioning) was added to the spec to cover the prompt sync work (T024, T113, T120).

## Architecture

```text
Browser (React SPA) ──REST + SSE──► app (FastAPI, one process) ─────────────────────────────┐
                                     │                                                       │
   ingestion/ ─► chunking/ (tree-sitter → Documents) ─► guardrails/redaction (detect-secrets)│
        │                    └─► ModelFactory.embeddings ─► LiteLLM ─► Gemini / any provider │
        └─► overview/                                                                        │
   chat/ (LangChain LCEL):                                                                   │
     NeMo input rail ─► history-aware rewrite ─► Vector/Lexical/Symbol retrievers            │
       ─► EnsembleRetriever (RRF) + symbol pin ─► pack ─► NeMo retrieval rail                │
       ─► answer (streaming) ─► NeMo output rail (secret mask) ─► citation validation        │
   storage/ (SQLAlchemy) ─────────────► postgres (pgvector, tsvector)                        │
   Langfuse CallbackHandler + SDK ────► langfuse-web ─► langfuse-worker ─► clickhouse/redis/minio
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Compose services**:
- `app`: port 8000;
- `postgres`: pgvector image; creates the `codecompass` and `langfuse` databases;
- `langfuse-web`: port 3000, created headless through the `LANGFUSE_INIT_*` env vars;
- `langfuse-worker`, `clickhouse`, `redis`, `minio`.

All services have healthchecks. `app` depends on `postgres` being healthy. It does *not*
wait for Langfuse, which fails open.

## Project Structure

### Documentation (this feature)

```text
specs/001-code-assistant/
├── spec.md
├── plan.md              # this file
├── research.md          # Phase 0: decisions R1–R20
├── data-model.md        # Phase 1: entities, state machine, Langfuse trace shape, config
├── quickstart.md        # Phase 1: run + validation scenarios
├── contracts/
│   ├── http-api.md      # REST + SSE contract
│   ├── llm-provider.md  # ModelFactory (Constitution VI)
│   └── eval-dataset.md  # eval YAML, Langfuse dataset runs, metrics
└── tasks.md             # Phase 2 (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
backend/
├── pyproject.toml                # deps + ruff/mypy/pytest config; uv.lock alongside
├── alembic.ini, migrations/      # Alembic (schema, pgvector extension, indexes)
├── src/codecompass/
│   ├── main.py                   # app factory, routers, SPA mount, startup checks (NFR-007), recovery (R14), prompt sync
│   ├── config.py                 # Settings (pydantic-settings), the only place env is read (NFR-005)
│   ├── api/                      # codebases.py, conversations.py, chat.py (SSE), traces.py, messages.py, health.py, errors.py, schemas.py
│   ├── storage/                  # db.py (async engine/session), models.py (SQLAlchemy), repositories/
│   ├── ingestion/                # sources.py (GitHub tarball, zip; safe extract), filters.py, pipeline.py (stages, progress, atomic swap)
│   ├── chunking/                 # treesitter_chunker.py, generic_chunker.py, identifiers.py, documents.py (→ LangChain Document)
│   ├── retrieval/                # vector.py, lexical.py, symbol.py (BaseRetrievers), hybrid.py (EnsembleRetriever + symbol pin), packer.py, precheck.py
│   ├── chat/                     # chain.py (LCEL), rewrite.py, history.py (DB ↔ BaseMessage), citations.py, streaming.py (SSE events)
│   ├── guardrails/
│   │   ├── redaction.py          # detect-secrets detector + redact (FR-030; reused by output rail, FR-033)
│   │   ├── injection.py          # heuristics (FR-031)
│   │   ├── actions.py            # NeMo custom actions: retrieval rail, output secret mask
│   │   ├── rails.py              # LLMRails setup with ModelFactory models; invoke input/retrieval/output rails
│   │   └── config/               # NeMo config.yml, rails.co (Colang), prompts.yml (self-check input = topical policy)
│   ├── prompts/                  # answer.yaml, rewrite.yaml, starter_questions.yaml (git source of truth → synced to Langfuse)
│   ├── llm/                      # factory.py (ModelFactory, ChatLiteLLM, LiteLLM embeddings)
│   ├── overview/                 # languages.py, structure.py, entrypoints.py, dependencies.py, routes.py, starters.py
│   ├── observability/            # langfuse_client.py (handler, fail-open), prompt_sync.py, trace_reader.py (Langfuse → FR-040 view), logging.py
│   └── eval/                     # __main__.py (CLI), dataset.py (YAML ↔ Langfuse dataset), metrics.py (hit-rate, citations), ragas_eval.py, report.py
└── tests/
    ├── unit/                     # named by requirement, e.g. test_fr015_symbol_pin.py, test_fr030_redaction.py, test_fr033_output_rail.py
    ├── integration/              # API + SSE via httpx ASGITransport; testcontainers Postgres; FakeModelFactory; NeMo with fakes
    ├── fakes/                    # fake_models.py (scripted streaming chat fake, hashed embeddings)
    └── fixtures/                 # mini_python_repo/, mini_ts_repo/, guardrail_repo/ (fake secrets + injected comment), unsafe archives
frontend/
├── package.json, vite.config.ts, tailwind.config.ts, tsconfig.json
└── src/
    ├── api/                      # client.ts (typed fetch), queries.ts (TanStack Query hooks), sse.ts (POST-SSE parser)
    ├── components/               # Sidebar, IngestForm, IngestProgress, Overview, Chat, MessageView, CitationChip, CodeViewer, TraceDrawer, HealthBanner, FeedbackButtons
    ├── hooks/                    # useChatStream, useTheme
    ├── App.tsx, main.tsx
    └── **/*.test.ts(x)           # Vitest, colocated
eval/
├── datasets/fastapi-template-v1.yaml
└── reports/                      # generated; committed selectively as evidence
infra/
└── postgres/init.sql             # creates the codecompass + langfuse databases, CREATE EXTENSION vector
Dockerfile                        # multi-stage: node build → python runtime serving API + dist/
docker-compose.yml                # app, postgres, langfuse-web, langfuse-worker, clickhouse, redis, minio (pinned tags, healthchecks)
.env.example                      # every setting with defaults; infra secrets as dev placeholders
Makefile                          # init-env, up, down, test, lint, fmt, eval, migrate
```

**Structure Decision**: web application (`backend/` + `frontend/`) shipped as one app image,
running next to standard platform services in Compose. Modules are split by RAG stage so each
brief topic (chunking, embeddings, retrieval, prompts, context, guardrails, quality,
observability) has one folder a reviewer can open (SC-005).

## Requirement → module map

| Requirements | Module(s) | Key tests |
|---|---|---|
| FR-001, FR-002, FR-005, NFR-004 | `ingestion/sources.py`, `pipeline.py` | unit: URL parsing, unsafe zip/tar entries; integration: over-limit rejection leaves 0 rows; zip upload → ready |
| FR-003, FR-004 | `ingestion/filters.py`, `pipeline.py` | unit: each skip reason; integration: summary shape and progress |
| FR-006, FR-007 | `storage/`, `api/codebases.py`, `retrieval/` | integration: two codebases isolated; delete cascades (and Langfuse delete called) |
| NFR-002 | `chunking/` | unit: py/js/ts spans exact; oversize split; generic windows; chunk text == file lines |
| FR-010, FR-011, FR-013 | `chat/chain.py`, `citations.py`, `streaming.py`, `retrieval/precheck.py` | unit: citation parse/validate; integration: SSE event order; not-found pre-check skips LLM |
| FR-012 | `api/codebases.py` files endpoint, `CodeViewer` | integration: redacted content; vitest: highlight range |
| FR-014, FR-016 | `chat/rewrite.py`, `history.py`, `api/conversations.py` | integration: follow-up uses history; persistence across app re-creation |
| FR-015 | `retrieval/symbol.py`, `hybrid.py`, `chunking/identifiers.py` | unit: identifier query pins the defining chunk despite unrelated vector scores |
| FR-020, FR-021 | `overview/` | unit: routes/deps/entry points on fixtures; starter fallback |
| FR-030 | `guardrails/redaction.py`, `ingestion/pipeline.py` | unit: every fixture secret redacted, line numbers preserved |
| FR-031 | `guardrails/injection.py`, `actions.py`, `config/` | unit: flagging; integration: retrieval rail marks chunk; live smoke: injected instruction not followed |
| FR-032 | NeMo input rail (`config/prompts.yml`, `rails.py`) | integration (fake self-check model): off-topic → `declined`; live smoke on real model |
| FR-033 | `guardrails/actions.py` output rail | unit: secret split across stream deltas masked; SC-004 integration sweep (prompt, answer, viewer, trace payload) |
| FR-043 | `prompts/`, `observability/prompt_sync.py` | unit: prompt load + version hash; integration: trace links prompt version |
| FR-040, FR-041 | `observability/`, `api/traces.py`, `api/messages.py` | integration: mock Langfuse receives spans with every FR-040 field; feedback stored + score sent; fail-open when Langfuse is down |
| FR-042, SC-002, SC-003 | `eval/` | unit: metric maths, dataset validation; `make eval` (live) |
| NFR-001 | `chat/`, `guardrails/rails.py` | `latency_ms` per step in trace; eval p50 |
| NFR-003, NFR-005, NFR-007 | `Dockerfile`, compose, `config.py`, `main.py`, `HealthBanner` | integration: health states with fakes; manual compose run + timing |
| NFR-006 | `frontend/` | vitest a11y roles; manual keyboard pass |

## Build order (maps to `/speckit-tasks` phases)

1. **Foundation**:
   - repo skeleton, config, `ModelFactory` + fakes;
   - SQLAlchemy models + Alembic;
   - compose with Postgres + the Langfuse stack (headless init), `make init-env`;
   - Langfuse client (fail-open) + prompt sync;
   - health checks, Makefile, `make test lint`.
2. **US-1 Ingest** (+ FR-030 redaction, so nothing is stored unredacted): sources, filters,
   chunking, embeddings, atomic swap, progress, ingestion trace, UI ingest form, progress and
   summary.
3. **US-2 Chat**: retrievers + ensemble, rewrite, LCEL chain, streaming SSE, citations,
   conversations, code viewer.
4. **US-3 Guardrails**:
   - **spike** on NeMo streaming output rails with `ChatLiteLLM` (fallback in R9);
   - then input, retrieval and output rails;
   - fixture sweep.
5. **US-5 Overview**: extractors, starter questions, overview screen.
6. **US-4 Observability & eval**: trace reader + drawer, feedback scores, eval dataset (author
   verifies expected files), Langfuse dataset runs, RAGAS, `make eval`.
7. **Polish**: dark mode, keyboard pass, edge-case messages, cold-start timing, README
   skeleton (fact sections only; the author writes the opinion sections).

Each story ends with `spec-reviewer` PASS → `python scripts/cross-review.py` → commit.

## Dependencies

CLAUDE.md requires a reason for every dependency. Versions are pinned in `uv.lock`,
`package-lock.json` and compose image tags.

| Package / image | Where | Why (requirement) |
|---|---|---|
| fastapi, uvicorn[standard], python-multipart | backend | HTTP API, typed schemas, SSE (FR-010), zip upload (FR-002) |
| pydantic-settings | backend | all config from env, validated (NFR-005) |
| sqlalchemy[asyncio], asyncpg or psycopg[binary], alembic, pgvector (python) | backend | typed persistence, versioned migrations, vector column (FR-007, FR-016, R5) |
| langchain-core, langchain (≥ 1.0) | backend | LCEL chain, `Document`/`BaseRetriever`, `EnsembleRetriever` RRF, prompt templates (R6, R12) |
| langchain-litellm, litellm | backend | provider-agnostic chat + embeddings, retries, cost (VI, R3) |
| nemoguardrails | backend | input/retrieval/output rails (FR-031, FR-032, FR-033, R9) |
| langfuse | backend | traces, sessions, prompt versions, feedback scores, datasets (FR-040–042, R10) |
| ragas | backend | standard faithfulness / context metrics in eval (FR-042, R11) |
| tree-sitter, tree-sitter-python, tree-sitter-javascript, tree-sitter-typescript | backend | structure-aware chunking with exact lines (NFR-002, FR-011), route detection (FR-020) |
| detect-secrets | backend | secret detection for redaction and output rail (FR-030, FR-033) |
| pathspec | backend | correct `.gitignore` semantics (FR-003) |
| httpx | backend | streamed GitHub tarball with byte cap (FR-001, FR-005); Langfuse trace reads; test client |
| pyyaml | backend | eval dataset and prompt files (FR-042, R10) |
| pytest, pytest-asyncio, testcontainers[postgres], ruff, mypy | backend dev | tests on real Postgres, lint, types (VII, QG4) |
| react, react-dom, vite, typescript | frontend | SPA + build (B-01) |
| tailwindcss | frontend | consistent styling, dark mode (NFR-006) |
| @tanstack/react-query | frontend | polling progress, cache invalidation across codebases/conversations (FR-004, FR-016) |
| react-markdown, remark-gfm | frontend | render streamed markdown safely, no raw HTML |
| prism-react-renderer | frontend | code viewer highlighting + line ranges (FR-012) |
| vitest, @testing-library/react, jsdom, eslint | frontend dev | tests and lint (VII, QG4) |
| @vitejs/plugin-react, postcss, autoprefixer, @types/react, @types/react-dom, @eslint/js, typescript-eslint, eslint-plugin-react-hooks, globals, @testing-library/jest-dom, @testing-library/user-event | frontend dev | companions the tools above need: Vite JSX transform, Tailwind's PostCSS pipeline, React types, the ESLint flat config for TS + hooks, DOM matchers and keyboard simulation for accessibility tests (NFR-006). Added during T003 |
| types-pyyaml | backend dev | mypy --strict type stubs for pyyaml. Added during T002 |
| `pgvector/pgvector:pg16` | compose | app DB + vectors + Langfuse metadata DB (R5) |
| `langfuse/langfuse`, `langfuse/langfuse-worker`, `clickhouse/clickhouse-server`, `redis`, `minio/minio` | compose | Langfuse v4 self-hosted reference stack (R10) |

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Cold start > 5 min (SC-001) because of Langfuse image pulls | pinned tags; measured and reported in README; app usable as soon as `app` + `postgres` are healthy (Langfuse fails open) |
| NeMo streaming output rails don't fit the LCEL/SSE flow | spike first in US-3; fallback = `RunnableRails` for input + own line-buffered filter calling the same action (R9) |
| NeMo input rail adds latency against NFR-001 | fast model, short self-check prompt; `latency_ms.input_rails` tracked; eval reports p50 |
| Library churn (LangChain 1.x, NeMo 0.x, RAGAS) | exact pins in `uv.lock`; LangChain kept out of domain modules; live smoke tests catch breakage |
| Free-tier rate limits (embedding at ingestion, judge in eval) | batched embeds + LiteLLM backoff; configurable batch size; demo repo is small |
| Poor retrieval on reviewer's repo | hybrid + symbol retrieval; trace drawer and Langfuse show why; eval hit-rate tracked; optional reranker by config |
| Infra secrets leaked through `.env.example` | dev placeholders only; `make init-env` generates random values; `.env` git-ignored |

## Optional upgrades (⚑ author may pull into v1)

1. **LiteLLM proxy** service: virtual keys, budgets, model fallbacks, central spend tracking.
2. **Reranker** (cross-encoder or a managed rerank API via LangChain) behind a config flag.
3. **Presidio PII rails** in NeMo.
4. **LangGraph agent** for multi-hop questions ("trace this request end to end").

## Complexity Tracking

| Violation | Why needed | Simpler alternative rejected because |
|---|---|---|
| Langfuse v4 stack adds 5 containers, including Redis + a worker (a queue), against Constitution II "no microservices/queues" | Author direction (2026-11-16): enterprise-grade observability, with traces, sessions, prompt versioning, feedback scores and dataset experiments, self-hosted so no data leaves the machine. These are third-party platform components, not our services; our app remains one process | Local trace table (rev. 1): no dashboards, prompt versioning or experiment comparison. Langfuse Cloud: a signup per reviewer, and data leaves the machine |
| NeMo input rail adds an LLM call on the critical path (NFR-001 pressure) | Standard, configurable policy layer for topic and jailbreak control (FR-032) and a framework for retrieval/output rails (FR-031, FR-033) | Plain-code rails folded into the rewrite call (rev. 1): faster, but no policy framework |
