# Contract: HTTP API

**Feature**: `001-code-assistant` | Base path: `/api` | Format: JSON unless noted.
FastAPI also serves the generated OpenAPI document at `/api/openapi.json`. This file is the
human-readable contract, and integration tests (`backend/tests/integration/`) assert it.

**Error shape** (all non-2xx): `{"error": {"code": "<snake_case>", "message": "<user-facing>"}}`

| Code | HTTP | When |
|---|---|---|
| `invalid_github_url` | 422 | URL is not `https://github.com/<owner>/<repo>[/tree/<ref>]` |
| `repo_not_found` | 404 | GitHub 404: private, misspelt or deleted (edge case) |
| `github_rate_limited` | 503 | GitHub 403/429 |
| `repo_too_large` | 413 | over `MAX_FILES` / `MAX_INDEX_BYTES` / download cap (FR-005) |
| `invalid_archive` | 422 | not a zip, corrupt, unsafe paths only, zip bomb |
| `no_supported_files` | 422 | nothing indexable after filtering (edge case) |
| `codebase_not_ready` | 409 | chat while ingesting / never ingested |
| `llm_unavailable` | 503 | key missing/invalid or provider down (NFR-007) |
| `trace_unavailable` | 503 | Langfuse unreachable when fetching a trace |
| `not_found` | 404 | unknown codebase/conversation/message/trace/file |
| `invalid_request` | 422 | request body or parameters fail validation (message names the fields) |
| `http_error` | 4xx | other framework-level errors, e.g. 405 method not allowed |
| `internal_error` | 500 | unexpected server error; details are only in the server logs |

---

## Health (NFR-007)

### `GET /api/health`
`200` → `{"status": "ok"|"degraded", "llm": "ok"|"missing"|"invalid"|"unreachable", "database": "ok"|"unreachable", "langfuse": "ok"|"unreachable"|"disabled", "llm_help_url": "<README anchor>", "langfuse_ui_url": "http://localhost:3000", "version": "x.y.z"}`
`degraded` whenever any component is `missing`, `invalid` or `unreachable` (`langfuse: "disabled"` is a deliberate setting and does not degrade). `llm` or `database` not ok → blocking UI
banner. `langfuse` not ok → non-blocking warning (chat still works, research R10).

## Codebases (FR-001…007, FR-020/021)

### `POST /api/codebases/github`
Body: `{"url": "https://github.com/fastapi/full-stack-fastapi-template", "ref": null}`
→ `202` `Codebase` (status `queued`). URL syntax is validated synchronously. Existence and
size checks happen in the job, and failures show up as `status: "failed"` with `error`.

### `POST /api/codebases/zip`
`multipart/form-data`, field `file` (.zip, ≤ `MAX_UPLOAD_BYTES`) → `202` `Codebase`.

### `GET /api/codebases`
→ `200` `{"items": [Codebase]}`, newest first.

### `GET /api/codebases/{id}`
→ `200` `Codebase`. The UI polls this every 1 s for progress.

### `POST /api/codebases/{id}/reingest`
→ `202` `Codebase`. Conversations are kept (edge case: re-ingest).

### `DELETE /api/codebases/{id}`
→ `204`. Cascades to ingestions, files, chunks, conversations and messages (FR-007), and
deletes the codebase's Langfuse traces (best effort, logged). `409` while ingesting.

### `GET /api/codebases/{id}/overview`
→ `200` `Overview` (see [data-model.md](../data-model.md#overview-json-on-ingestion)); `409` if not ready.

### `GET /api/codebases/{id}/files?path=<relpath>`
→ `200` `{"path", "language", "line_count", "content", "redaction_count"}`. Returns the
**redacted** content of the active ingestion (FR-012, FR-030). `path` must exactly match an
indexed file; no filesystem access (FR-002).

**`Codebase` object**
```json
{
  "id": "…", "name": "fastapi/full-stack-fastapi-template",
  "source_type": "github", "source_url": "…", "source_ref": null, "commit_sha": "abc123…",
  "status": "queued|ingesting|ready|failed", "error": null, "reingest_required": false,
  "progress": {"stage": "embedding", "files_done": 120, "files_total": 310,
               "chunks_done": 800, "chunks_total": 1900},
  "summary": {"indexed": 310, "skipped_by_reason": {"lockfile": 2, "binary": 14},
              "skipped": [{"path": "frontend/package-lock.json", "reason": "lockfile"}],
              "bytes_indexed": 1830000},
  "created_at": "…", "updated_at": "…"
}
```
`summary.skipped` is capped at 500 entries; `skipped_by_reason` is always complete.
`reingest_required` is true when the active ingestion used a different embedding model or
dimension than the current settings. Chat then returns `409 codebase_not_ready`.

## Conversations (FR-014, FR-016)

### `GET /api/codebases/{id}/conversations`
→ `200` `{"items": [{"id", "title", "created_at", "updated_at", "message_count"}]}` sorted by `updated_at desc`.

### `POST /api/codebases/{id}/conversations`
→ `201` `{"id", "title": "New conversation", …}`

### `GET /api/conversations/{id}`
→ `200` `{"id", "codebase_id", "title", "messages": [Message]}`

### `DELETE /api/conversations/{id}`
→ `204`

**`Message` object**
```json
{
  "id": "…", "seq": 3, "role": "assistant", "status": "complete|error|declined|not_found|unverified",
  "content": "Users are created in [backend/app/crud.py:14-29] …",
  "citations": [{"path": "backend/app/crud.py", "start_line": 14, "end_line": 29,
                 "stale": false}],
  "trace_id": "…", "feedback": 1,
  "usage": {"tokens_in": 2310, "tokens_out": 180, "cost_usd": 0.0004,
            "latency_ms": {"first_token": 1450, "total": 3900}},
  "created_at": "…"
}
```
`stale` is computed on read by comparing `content_hash` with the current file (research R15).

## Chat (FR-010…015, FR-030…033, FR-040)

### `POST /api/conversations/{id}/messages`
Body: `{"content": "Where is the user model defined?"}`
Response: `200`, `Content-Type: text/event-stream`. The user message is saved before
streaming starts, and the assistant message is saved when `done` (or `error`) is sent.

Events (each `event: <name>\ndata: <json>\n\n`), in order:

| Event | Data | Notes |
|---|---|---|
| `meta` | `{"user_message_id", "assistant_message_id", "trace_id", "rewritten_query"}` | always first |
| `token` | `{"text": "…"}` | 0..n; text has **already passed the output filter** (FR-033) |
| `citations` | `{"citations": [Citation]}` | once, after the last token; validated only (R7) |
| `done` | `{"status": "complete"\|"declined"\|"not_found"\|"unverified", "usage": {"tokens_in", "tokens_out", "cost_usd"}, "latency_ms": {"first_token", "total"}}` | terminal |
| `error` | `{"code", "message", "partial": true\|false}` | terminal; e.g. provider failed mid-stream (edge case) |

Declined (FR-032) and pre-check not-found (FR-013) answers arrive as a few `token` events
holding the fixed message, then `done` with the matching status.

## Traces & feedback (FR-040, FR-041)

### `GET /api/traces/{id}`
Served by the backend from the Langfuse public API and normalised into the FR-040 fields
([data-model.md](../data-model.md#trace-external-langfuse)):
```json
{
  "id": "…", "langfuse_url": "http://localhost:3000/project/…/traces/…",
  "query": "…", "rewritten_query": "…", "identifiers": ["get_password_hash"],
  "guardrails": {"input": "allowed|declined", "injection_flagged_chunks": [12],
                 "output_redactions": 0, "not_found_precheck": false},
  "retrieval": [{"path", "start_line", "end_line", "vector_rank", "vector_score",
                 "lexical_rank", "lexical_score", "symbol_hit", "fused_score", "packed"}],
  "prompt": [{"role": "system", "content": "…"}],
  "model": "…", "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
  "latency_ms": {"input_rails", "rewrite", "retrieve", "first_token", "generate", "total"},
  "citations_valid": 2, "citations_invalid": 0, "feedback": 1
}
```
- `202` `{"status": "processing"}` while Langfuse is still ingesting it (async; the UI retries).
- `503` `trace_unavailable` if Langfuse is unreachable. The message's local `usage` is still
  returned on the Message object.

### `PUT /api/messages/{id}/feedback`
Body: `{"value": 1|-1|null, "comment": "optional"}` → `204`. Saved on the message and sent
to Langfuse as score `user_feedback` on its trace (FR-041). A Langfuse failure is logged and
retried; the request still succeeds.

## Static

`GET /` and any non-`/api` path → the built SPA (`index.html`), so client-side refresh works.
