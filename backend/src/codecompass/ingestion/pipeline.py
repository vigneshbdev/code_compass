"""The ingestion pipeline (FR-001…FR-007, FR-030, research R14, task T054).

Stages: downloading → filtering → chunking → embedding → overview → finalizing.

- One ingestion runs at a time (global semaphore); others wait as `queued`.
- Secrets are redacted before anything is stored or embedded (FR-030).
- Limits are checked before any embedding (FR-005), so an over-limit repo costs nothing.
- All rows are written under a new ingestion id, and one final transaction activates it and
  removes the previous ingestion. A failure deletes the new rows, so nothing half-indexed is
  ever queryable. Startup recovery resolves work interrupted by a restart.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

import httpx

from codecompass.api.errors import AppError, ErrorCode
from codecompass.chunking import chunk_file, detect_language
from codecompass.chunking.documents import ChunkDraft, estimate_tokens
from codecompass.config import Settings
from codecompass.guardrails.injection import is_injection
from codecompass.guardrails.redaction import SecretDetector
from codecompass.ingestion.filters import Skip, SourceFile, select_files
from codecompass.ingestion.pacing import REQUESTS_PER_WINDOW, EmbedPacer, token_batches
from codecompass.ingestion.sources import (
    GithubRef,
    fetch_github,
    parse_github_url,
    safe_extract_zip,
)
from codecompass.llm.factory import ModelFactory
from codecompass.observability.langfuse_client import LangfuseClient
from codecompass.overview.dependencies import dependencies
from codecompass.overview.languages import languages
from codecompass.overview.starters import starter_questions
from codecompass.storage.db import Database
from codecompass.storage.repositories import chunks as chunk_repo
from codecompass.storage.repositories import codebases as codebase_repo
from codecompass.storage.repositories import ingestions as ingestion_repo

logger = logging.getLogger(__name__)

SKIPPED_LIST_CAP = 500  # contracts/http-api.md: summary.skipped is capped
PREPARE_BATCH_FILES = 25
GITHUB_TIMEOUT_SECONDS = 60
UNEXPECTED = "Ingestion failed unexpectedly. Check the server logs."


@dataclass
class Fetched:
    root: Path
    skipped: list[Skip] = field(default_factory=list)
    commit_sha: str | None = None


Source = Callable[[Path], Awaitable[Fetched]]


@dataclass
class PreparedFile:
    path: str
    language: str
    content: str  # redacted
    redaction_count: int
    chunks: list[ChunkDraft]


def _prepare(files: list[SourceFile], detector: SecretDetector) -> list[PreparedFile]:
    """CPU-bound: redact (FR-030), then chunk the redacted text. Runs in a worker thread."""
    prepared: list[PreparedFile] = []
    for f in files:
        redacted, count = detector.redact(f.text)
        prepared.append(
            PreparedFile(
                f.path, detect_language(f.path), redacted, count, chunk_file(f.path, redacted)
            )
        )
    return prepared


def _summary(kept: list[SourceFile], skipped: list[Skip]) -> dict[str, Any]:
    return {
        "indexed": len(kept),
        "skipped": [{"path": s.path, "reason": s.reason} for s in skipped[:SKIPPED_LIST_CAP]],
        "skipped_by_reason": dict(Counter(s.reason for s in skipped)),
        "bytes_indexed": sum(f.size for f in kept),
    }


def _check_limits(kept: list[SourceFile], settings: Settings) -> None:
    if not kept:
        raise AppError(ErrorCode.NO_SUPPORTED_FILES, "No supported source files were found.")
    if len(kept) > settings.max_files:
        raise AppError(
            ErrorCode.REPO_TOO_LARGE,
            f"The codebase has {len(kept)} indexable files; "
            f"the limit is {settings.max_files} files.",
        )
    total = sum(f.size for f in kept)
    if total > settings.max_index_bytes:
        raise AppError(
            ErrorCode.REPO_TOO_LARGE,
            f"The codebase has {total / 1_000_000:.1f} MB of indexable content; the limit is "
            f"{settings.max_index_bytes / 1_000_000:.0f} MB.",
        )


class IngestionService:
    def __init__(
        self,
        db: Database,
        models: ModelFactory,
        settings: Settings,
        langfuse: LangfuseClient,
        http_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._db = db
        self._models = models
        self._settings = settings
        self._langfuse = langfuse
        self._http_factory = http_factory or (
            lambda: httpx.AsyncClient(timeout=GITHUB_TIMEOUT_SECONDS)
        )
        self._lock = asyncio.Semaphore(1)
        self._tasks: set[asyncio.Task[None]] = set()
        self._detector = SecretDetector()

    # ── Submission ─────────────────────────────────────────────────────────────────────────

    def _upload_path(self, codebase_id: uuid.UUID) -> Path:
        return self._settings.data_dir / "uploads" / f"{codebase_id}.zip"

    async def submit_zip(self, filename: str, data: bytes) -> uuid.UUID:
        name = Path(filename or "upload.zip").stem or "upload"
        async with self._db.sessions() as session, session.begin():
            codebase = await codebase_repo.create(session, name=name, source_type="zip")
            codebase_id = codebase.id
        path = self._upload_path(codebase_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)  # kept so the codebase can be re-ingested or retried
        self._schedule(codebase_id)
        return codebase_id

    async def submit_github(self, url: str, ref: str | None) -> uuid.UUID:
        parsed = parse_github_url(url)
        async with self._db.sessions() as session, session.begin():
            codebase = await codebase_repo.create(
                session,
                name=f"{parsed.owner}/{parsed.repo}",
                source_type="github",
                source_url=url.strip(),
                source_ref=ref or parsed.ref,
            )
            codebase_id = codebase.id
        self._schedule(codebase_id)
        return codebase_id

    async def reingest(self, codebase_id: uuid.UUID) -> None:
        async with self._db.sessions() as session, session.begin():
            codebase = await codebase_repo.get(session, codebase_id)
            if codebase.status in codebase_repo.IN_PROGRESS:
                raise AppError(
                    ErrorCode.CODEBASE_NOT_READY, "This codebase is already being ingested."
                )
            await codebase_repo.set_status(session, codebase.id, "queued")
        self._schedule(codebase_id)

    def forget_upload(self, codebase_id: uuid.UUID) -> None:
        self._upload_path(codebase_id).unlink(missing_ok=True)

    def _schedule(self, codebase_id: uuid.UUID) -> None:
        task = asyncio.create_task(self._run(codebase_id), name=f"ingest-{codebase_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, codebase_id: uuid.UUID) -> None:
        async with self._lock:
            await self._ingest(codebase_id)

    # ── Sources ────────────────────────────────────────────────────────────────────────────

    async def _source(self, codebase_id: uuid.UUID) -> Source:
        async with self._db.sessions() as session:
            codebase = await codebase_repo.get(session, codebase_id)
            source_type, url, ref = codebase.source_type, codebase.source_url, codebase.source_ref

        if source_type == "zip":
            upload = self._upload_path(codebase_id)

            async def from_zip(workdir: Path) -> Fetched:
                if not upload.exists():
                    raise AppError(
                        ErrorCode.INVALID_ARCHIVE, "The original upload is no longer available."
                    )
                result = await asyncio.to_thread(
                    safe_extract_zip, upload, workdir / "src", self._settings
                )
                return Fetched(result.root, result.skipped, None)

            return from_zip

        parsed = parse_github_url(url or "")
        github_ref = GithubRef(parsed.owner, parsed.repo, ref or parsed.ref)

        async def from_github(workdir: Path) -> Fetched:
            async with self._http_factory() as http:
                result = await fetch_github(
                    github_ref, settings=self._settings, dest=workdir, http=http
                )
            return Fetched(result.root, result.skipped, result.commit_sha)

        return from_github

    # ── The pipeline ───────────────────────────────────────────────────────────────────────

    async def _progress(self, ingestion_id: uuid.UUID, **fields: Any) -> None:
        async with self._db.sessions() as session, session.begin():
            await ingestion_repo.update_progress(session, ingestion_id, **fields)

    async def _ingest(self, codebase_id: uuid.UUID) -> None:
        settings = self._settings
        workdir = settings.data_dir / f"ingest-{uuid.uuid4().hex}"
        trace = self._langfuse.start_trace("ingestion", {"codebase_id": str(codebase_id)})
        ingestion_id: uuid.UUID | None = None
        try:
            async with self._db.sessions() as session, session.begin():
                ingestion = await ingestion_repo.create(
                    session,
                    codebase_id,
                    embedding_model=settings.embedding_model,
                    embedding_dim=settings.embedding_dim,
                    langfuse_trace_id=trace.trace_id,
                )
                ingestion_id = ingestion.id
                await codebase_repo.set_status(session, codebase_id, "ingesting")

            source = await self._source(codebase_id)
            fetched = await source(workdir)
            await self._progress(ingestion_id, stage="filtering", commit_sha=fetched.commit_sha)

            selection = await asyncio.to_thread(select_files, fetched.root, settings)
            kept, skipped = selection.kept, fetched.skipped + selection.skipped
            _check_limits(kept, settings)  # FR-005: before any embedding

            await self._progress(ingestion_id, stage="chunking", files_total=len(kept))
            prepared: list[PreparedFile] = []
            for i in range(0, len(kept), PREPARE_BATCH_FILES):
                batch = kept[i : i + PREPARE_BATCH_FILES]
                prepared.extend(await asyncio.to_thread(_prepare, batch, self._detector))
                await self._progress(ingestion_id, files_done=len(prepared))

            total_chunks = sum(len(p.chunks) for p in prepared)
            async with self._db.sessions() as session, session.begin():
                file_ids = await chunk_repo.insert_files(
                    session,
                    ingestion_id,
                    [
                        {
                            "path": p.path,
                            "language": p.language,
                            "line_count": len(p.content.splitlines()),
                            "size_bytes": len(p.content.encode()),
                            "content": p.content,
                            "redaction_count": p.redaction_count,
                        }
                        for p in prepared
                    ],
                )
                await ingestion_repo.update_progress(
                    session, ingestion_id, stage="embedding", chunks_total=total_chunks
                )

            await self._embed_and_store(ingestion_id, prepared, file_ids)

            await self._progress(ingestion_id, stage="overview")
            overview = await self._overview(prepared)
            summary = _summary(kept, skipped)
            async with self._db.sessions() as session, session.begin():
                await ingestion_repo.update_progress(
                    session, ingestion_id, summary=summary, overview=overview
                )
                await ingestion_repo.activate(session, codebase_id, ingestion_id)
            trace.end(output={"indexed": summary["indexed"], "chunks": total_chunks})
        except AppError as exc:
            trace.end(output={"error": exc.code.value}, level="ERROR")
            await self._fail(codebase_id, ingestion_id, exc.code.value, exc.message)
        except asyncio.CancelledError:
            # Shutdown: leave the rows; startup recovery resolves them consistently.
            raise
        except Exception:
            logger.exception("ingestion failed", extra={"data": {"codebase_id": str(codebase_id)}})
            trace.end(output={"error": "internal_error"}, level="ERROR")
            await self._fail(codebase_id, ingestion_id, "internal_error", UNEXPECTED)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _overview(self, prepared: list[PreparedFile]) -> dict[str, Any]:
        """FR-020/FR-021 from redacted content; starter questions never fail ingestion."""
        files = {p.path: p.content for p in prepared}
        overview: dict[str, Any] = {
            "languages": languages(files),
            "dependencies": dependencies(files),
        }
        questions, source = await starter_questions(self._models.chat("fast"), overview)
        return {**overview, "starter_questions": questions, "starter_source": source}

    async def _embed_and_store(
        self, ingestion_id: uuid.UUID, prepared: list[PreparedFile], file_ids: dict[str, int]
    ) -> None:
        embedder = self._models.embeddings()
        pending = [(p.path, c) for p in prepared for c in p.chunks]
        costs = [estimate_tokens(c.embed_text) for _, c in pending]
        pacer = EmbedPacer(  # NFR-004: free-tier keys have a tokens-per-minute cap
            self._settings.embed_tokens_per_minute, self._settings.embed_rate_limit_retries
        )
        done = 0
        # A request must fit well inside the minute budget even if our estimate undercounts.
        request_cap = self._settings.embed_tokens_per_minute // REQUESTS_PER_WINDOW
        for indexes in token_batches(costs, self._settings.embed_batch_size, request_cap):
            batch = [pending[i] for i in indexes]
            texts = [c.embed_text for _, c in batch]
            try:
                vectors = await pacer.run(
                    sum(costs[i] for i in indexes),
                    partial(embedder.aembed_documents, texts),
                )
            except Exception as exc:
                logger.exception("embedding failed")
                raise AppError(
                    ErrorCode.LLM_UNAVAILABLE,
                    "The embedding provider failed (rate limit, quota or key problem). "
                    "Retry in a minute.",
                ) from exc
            rows = [
                {
                    "file_id": file_ids[path],
                    "path": c.path,
                    "start_line": c.start_line,
                    "end_line": c.end_line,
                    "language": c.language,
                    "kind": c.kind,
                    "symbol": c.symbol,
                    "symbol_leaf": c.symbol_leaf,
                    "text": c.text,
                    "embed_text": c.embed_text,
                    "identifiers": c.identifiers,
                    "token_count": c.token_count,
                    "embedding": vector,
                    "injection_flag": is_injection(c.text),  # FR-031
                }
                for (path, c), vector in zip(batch, vectors, strict=True)
            ]
            done += len(rows)
            async with self._db.sessions() as session, session.begin():
                await chunk_repo.insert_chunks(session, ingestion_id, rows)
                await ingestion_repo.update_progress(session, ingestion_id, chunks_done=done)

    async def _fail(
        self, codebase_id: uuid.UUID, ingestion_id: uuid.UUID | None, code: str, message: str
    ) -> None:
        async with self._db.sessions() as session, session.begin():
            if ingestion_id is not None:
                await ingestion_repo.discard(session, ingestion_id)  # nothing half-indexed
            codebase = await codebase_repo.get(session, codebase_id)
            keep_previous = codebase.active_ingestion_id is not None
            await codebase_repo.set_status(
                session,
                codebase_id,
                "ready" if keep_previous else "failed",
                error=message,
                error_code=code,
            )

    # ── Lifecycle ──────────────────────────────────────────────────────────────────────────

    async def recover_on_startup(self) -> None:
        """Resolve work interrupted by a restart (spec edge case, research R14)."""
        async with self._db.sessions() as session, session.begin():
            for ingestion in await ingestion_repo.unfinished(session):
                await ingestion_repo.discard(session, ingestion.id)
            for codebase in await ingestion_repo.stuck_codebases(session):
                await codebase_repo.set_status(
                    session,
                    codebase.id,
                    "ready" if codebase.active_ingestion_id else "failed",
                    error=ingestion_repo.RESTART_MESSAGE,
                )

    async def shutdown(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
