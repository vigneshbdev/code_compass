# Data Model: Code Documentation Assistant (Phase 1)

**Feature**: `001-code-assistant` | **Date**: 2026-11-16 (rev. 2) | **Plan**: [plan.md](plan.md)

Application state lives in Postgres 16 (database `codecompass`, pgvector extension), managed
by SQLAlchemy 2 models and Alembic migrations ([research R2, R5](research.md)). **Traces live
in Langfuse** ([R10](research.md#r10-observability-langfuse-fr-040-fr-041-constitution-v)); the
app keeps only the trace ID, a usage summary and feedback. IDs are UUIDs unless noted.
Timestamps are `timestamptz`. Foreign keys use `ON DELETE CASCADE`, so deleting a codebase
deletes everything below it (FR-007).

```text
Codebase 1 ──< Ingestion 1 ──< File 1 ──< Chunk (embedding vector, search tsvector)
    │              (active_ingestion_id)
    └──< Conversation 1 ──< Message 1 ──< Citation
                               └── trace_id ──► Langfuse trace (external)
```

---

## Codebase

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | text | `owner/repo` for GitHub, zip filename stem for uploads |
| source_type | text (enum) | `github` \| `zip` |
| source_url | text? | as given (null for zip) |
| source_ref | text? | branch/tag/commit requested |
| status | text (enum) | `queued` \| `ingesting` \| `ready` \| `failed` |
| active_ingestion_id | uuid? FK → Ingestion, `ON DELETE SET NULL` | null until the first success. One of two FKs that do not cascade (the other is `citation.chunk_id`): deleting an ingestion must not delete its codebase |
| error | text? | user-facing failure message |
| created_at, updated_at | timestamptz | |

**Validation**: `source_url` must match `https://github.com/<owner>/<repo>[/tree/<ref>]`
(FR-001). Zip uploads must be ≤ `MAX_UPLOAD_BYTES` and a valid zip (FR-002).

**State machine**:

```text
create ──► queued ──► ingesting ──► ready ──(re-ingest)──► queued …
                          │
                          ▼
                       failed ──(retry)──► queued
```

- A failed re-ingest of a codebase that already has an active ingestion returns it to `ready`
  with `error` set; the old index stays queryable.
- Chat is allowed only when `active_ingestion_id` is set (`409` otherwise).
- On startup, `queued`/`ingesting` rows are resolved this way, and the rows of their
  unfinished ingestion are deleted (edge case: restart mid-ingestion).

## Ingestion

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| codebase_id | uuid FK | |
| commit_sha | text? | resolved GitHub commit (eval pinning, FR-042) |
| status | text (enum) | `running` \| `complete` \| `failed` |
| stage | text (enum) | `downloading` \| `filtering` \| `chunking` \| `embedding` \| `overview` \| `finalizing` |
| files_total, files_done, chunks_total, chunks_done | int | progress (FR-004) |
| summary | jsonb | `{indexed, skipped: [{path, reason}] (≤500), skipped_by_reason: {reason: n}, bytes_indexed}` |
| overview | jsonb? | see Overview |
| langfuse_trace_id | text? | ingestion trace (embedding cost and duration) |
| embedding_model | text | `EMBEDDING_MODEL` used for this ingestion (analysis U1) |
| embedding_dim | int | `EMBEDDING_DIM` used. If either differs from current settings, the codebase is reported `reingest_required` and chat is refused until it is re-ingested |
| started_at, finished_at | timestamptz | |

**Skip reasons** (enum, FR-003): `gitignored`, `denylisted_dir`, `lockfile`, `binary`,
`too_large`, `non_utf8`, `symlink`, `unsafe_path`, `private_key_file`.

## File

Redacted file contents. The code viewer reads from here (FR-012, FR-030).

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| ingestion_id | uuid FK | |
| path | text | POSIX, relative; `UNIQUE(ingestion_id, path)` |
| language | text | `python` \| `javascript` \| `typescript` \| `tsx` \| `markdown` \| … \| `text` |
| line_count, size_bytes | int | |
| content | text | **redacted**; the original is never stored |
| redaction_count | int | shown as a badge; values never shown |

## Chunk

The unit of retrieval and citation. Exposed to LangChain as a `Document` (`page_content` =
`text`, `metadata` = the other columns).

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| ingestion_id | uuid FK | btree index (retrieval filter) |
| file_id | bigint FK | |
| path | text | denormalised |
| start_line, end_line | int | 1-based inclusive; `1 ≤ start_line ≤ end_line ≤ file.line_count` |
| language | text | |
| kind | text (enum) | `function` \| `class` \| `method` \| `module` \| `section` \| `window` |
| symbol | text? | qualified, e.g. `UserService.create`; btree + lower() index (FR-015) |
| symbol_leaf | text? | e.g. `create`; indexed |
| text | text | redacted span text |
| embed_text | text | context header + text (what was embedded) |
| identifiers | text | split identifiers feeding `search` |
| search | tsvector (generated, `simple` config, from `text`, `identifiers`, `path`) | GIN index |
| embedding | vector(`EMBEDDING_DIM`) | cosine (`<=>`); HNSW index optional (R5) |
| token_count | int | context packing |
| injection_flag | bool | matched injection heuristics at ingestion (FR-031) |

**Invariant** (tested): `text` equals exactly lines `start_line..end_line` of `File.content`,
so a citation always opens the cited code.

## Overview (jsonb on Ingestion)

```json
{
  "languages": [{"language": "python", "files": 120, "lines": 9800}],
  "structure": [{"path": "backend", "files": 140, "children": [{"path": "backend/app", "files": 98}]}],
  "entry_points": [{"path": "backend/app/main.py", "line": 12, "reason": "FastAPI app instance"}],
  "dependencies": [{"manifest": "backend/pyproject.toml", "ecosystem": "pypi", "name": "fastapi", "spec": ">=0.114", "dev": false}],
  "routes": [{"method": "GET", "path": "/api/v1/users/{id}", "handler": "read_user", "file": "backend/app/api/routes/users.py", "line": 88, "framework": "fastapi"}],
  "starter_questions": ["How is authentication implemented?", "..."],
  "starter_source": "llm"
}
```

`starter_questions`: 3–5 items (FR-021). `starter_source`: `llm` or `template`.

## Conversation

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | also the Langfuse `session_id` |
| codebase_id | uuid FK | cascade (FR-007) |
| title | text | first question, ≤ 80 chars |
| created_at, updated_at | timestamptz | listed by `updated_at desc` (FR-016) |

## Message

| Field | Type | Notes |
|---|---|---|
| id | uuid PK | |
| conversation_id | uuid FK | |
| seq | int | `UNIQUE(conversation_id, seq)` |
| role | text (enum) | `user` \| `assistant` |
| content | text | assistant: the **output-rail-filtered** text actually shown (FR-033) |
| status | text (enum) | `complete` \| `error` \| `declined` \| `not_found` \| `unverified` (claim-making answer with no valid citation: Constitution III, analysis C4) |
| trace_id | text? | Langfuse trace ID (assistant only) |
| usage | jsonb? | `{tokens_in, tokens_out, cost_usd, latency_ms: {input_rails, rewrite, retrieve, first_token, total}}`; kept locally so core numbers survive a Langfuse outage |
| feedback | smallint? | `1` / `-1` / null (FR-041); also sent to Langfuse as score `user_feedback` |
| feedback_comment | text? | |
| created_at | timestamptz | |

## Citation

| Field | Type | Notes |
|---|---|---|
| id | bigint PK | |
| message_id | uuid FK | |
| path | text | |
| start_line, end_line | int | |
| chunk_id | bigint? | chunk it was validated against (null after re-ingest cleanup) |
| content_hash | text | sha256 of the cited lines at answer time (stale detection, R15) |
| ordinal | int | order in the answer |

Only **valid** citations are stored. Invalid ones are counted in the trace (score
`citations_invalid`).

## Trace (external: Langfuse)

One Langfuse trace per chat request (FR-040). The structure the app produces:

| Langfuse object | Name | Captures |
|---|---|---|
| trace | `chat` | input = raw query, output = filtered answer, `session_id` = conversation ID, metadata: codebase ID, message IDs, prompt versions |
| span | `input_rails` (NeMo) | on-topic / jailbreak decision, latency |
| generation | `rewrite` | standalone query, identifiers, model, tokens, cost |
| span | `retrieve.vector` / `.lexical` / `.symbol` | documents with ranks and scores |
| span | `fusion` | fused ranking, packed chunks, pre-check result |
| span | `retrieval_rails` | injection-flagged chunk IDs |
| generation | `answer` | final prompt (redacted content only), model, tokens, cost, time to first token |
| span | `output_rails` | redaction count |
| scores | `citations_valid`, `citations_invalid`, `user_feedback` | SC-003, FR-041 |

`GET /api/traces/{id}` normalises this into the flat FR-040 field list for the UI drawer
([contracts/http-api.md](contracts/http-api.md#traces--feedback-fr-040-fr-041)). Deleting a
codebase also deletes its traces through the Langfuse API (best effort, logged), so ingested
content does not outlive the codebase.

## Configuration (env via `pydantic-settings`, NFR-005)

- **App**: `DATA_DIR` (temporary extraction), `DATABASE_URL`, `STATIC_DIR` (built SPA),
  `LLM_HELP_URL` (NFR-007 banner link), `MAX_FILES`, `MAX_INDEX_BYTES`, `MAX_FILE_BYTES`,
  `MAX_DOWNLOAD_BYTES`, `MAX_UPLOAD_BYTES`, `MAX_ARCHIVE_ENTRIES` and `MAX_UNCOMPRESSED_BYTES`
  (zip-bomb guards, research R13),
  `RETRIEVAL_TOP_K`, `CONTEXT_MAX_CHUNKS`, `CONTEXT_MAX_TOKENS`, `RETRIEVAL_MIN_SCORE`,
  `EMBED_BATCH_SIZE`, `GITHUB_API_BASE`, `GITHUB_TOKEN` (optional).
- **Models**: `LLM_MODEL`, `LLM_FAST_MODEL`, `LLM_JUDGE_MODEL`, `EMBEDDING_MODEL`,
  `EMBEDDING_DIM`. The provider key (`GEMINI_API_KEY` or any LiteLLM-supported key) is read
  by LiteLLM straight from the environment, not by Settings.
- **Langfuse (app side)**: `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`,
  `LANGFUSE_UI_URL` (for deep links), `LANGFUSE_ENABLED`.
- **Langfuse server / infra** (compose only): `LANGFUSE_INIT_*`, `NEXTAUTH_SECRET`, `SALT`,
  `ENCRYPTION_KEY`, Postgres/ClickHouse/MinIO/Redis credentials. These are dev placeholders
  that `make init-env` replaces with random values.

Defaults appear only in `.env.example` and the settings class.
