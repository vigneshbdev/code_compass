"""`python -m codecompass.eval <dataset.yaml>` (`make eval`): FR-042, SC-002, SC-003, T147.

Ingests the pinned commit if needed, runs every question through the same chat pipeline as the
app, scores the results (custom metrics + RAGAS faithfulness), writes reports, syncs the dataset
to Langfuse and records the eval scores on each question's trace.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from codecompass.chat.service import ChatContext, ChatService
from codecompass.config import get_settings
from codecompass.eval.dataset import Dataset, DatasetError, Question, check_expected_files, load
from codecompass.eval.metrics import QuestionResult, hit, passes, summarise
from codecompass.eval.ragas_eval import score_faithfulness
from codecompass.eval.report import write
from codecompass.guardrails.rails import Guardrails
from codecompass.ingestion.pipeline import IngestionService
from codecompass.llm.factory import LiteLLMModelFactory
from codecompass.observability.langfuse_client import LangfuseClient
from codecompass.observability.logging import configure_logging
from codecompass.observability.prompt_sync import PromptRegistry
from codecompass.retrieval.hybrid import RetrievalResult
from codecompass.storage.db import Database
from codecompass.storage.models import Codebase, File, Ingestion
from codecompass.storage.repositories import conversations as conversation_repo

INGEST_POLL_SECONDS = 2
INGEST_TIMEOUT_SECONDS = 30 * 60


async def ensure_ingested(db: Database, ingestion: IngestionService, dataset: Dataset) -> Codebase:
    async with db.sessions() as session:
        stmt = (
            select(Codebase)
            .join(Ingestion, Ingestion.id == Codebase.active_ingestion_id)
            .where(Ingestion.commit_sha == dataset.commit)
        )
        existing = (await session.execute(stmt)).scalars().first()
    if existing is not None:
        return existing
    print(f"Ingesting {dataset.repo} at {dataset.commit[:7]}…", flush=True)
    codebase_id = await ingestion.submit_github(f"{dataset.repo}/tree/{dataset.commit}", None)
    waited = 0
    while waited < INGEST_TIMEOUT_SECONDS:
        await asyncio.sleep(INGEST_POLL_SECONDS)
        waited += INGEST_POLL_SECONDS
        async with db.sessions() as session:
            codebase = await session.get(Codebase, codebase_id)
            if codebase is not None and codebase.status == "ready":
                return codebase
            if codebase is not None and codebase.status == "failed":
                raise SystemExit(f"Ingestion failed: {codebase.error}")
    raise SystemExit("Ingestion timed out.")


async def indexed_paths(db: Database, ingestion_id: uuid.UUID | None) -> set[str]:
    async with db.sessions() as session:
        stmt = select(File.path).where(File.ingestion_id == ingestion_id)
        return set((await session.execute(stmt)).scalars())


async def ask(db: Database, chat: ChatService, codebase: Codebase, q: Question) -> QuestionResult:
    async with db.sessions() as session, session.begin():
        conversation = await conversation_repo.create(session, codebase.id)
        conversation_id = conversation.id
    assert codebase.active_ingestion_id is not None
    ctx = ChatContext(conversation_id, codebase.id, codebase.active_ingestion_id)
    for earlier in q.history:  # replay prior turns (FR-014)
        async for _ in chat.stream(ctx, earlier):
            pass

    seen: dict[str, RetrievalResult] = {}
    answer, status, citations = "", "error", 0
    first_token: int | None = None
    trace_id: str | None = None
    async for event in chat.stream(ctx, q.question, observer=lambda r: seen.update(result=r)):
        if event.name == "meta":
            trace_id = event.data.get("trace_id")
        elif event.name == "token":
            answer += str(event.data["text"])
        elif event.name == "citations":
            citations = len(event.data["citations"])
        elif event.name == "done":
            status = str(event.data["status"])
            first_token = event.data["latency_ms"].get("first_token")
    packed = seen["result"].packed if "result" in seen else []
    return QuestionResult(
        id=q.id,
        category=q.category,
        answerable=q.answerable,
        expected_files=list(q.expected_files),
        retrieved_files=[d.metadata["path"] for d in packed],
        status=status,
        valid_citations=citations,
        first_token_ms=first_token,
        answer=answer,
        question=q.question,
        contexts=[d.page_content for d in packed],
        trace_id=trace_id,
    )


def record_in_langfuse(
    langfuse: LangfuseClient, dataset: Dataset, results: list[QuestionResult], run: str
) -> None:
    """Sync the dataset and attach eval scores to each question's trace (fails open)."""
    client = langfuse.client
    if client is None:
        return
    try:
        client.create_dataset(
            name=dataset.label, metadata={"repo": dataset.repo, "commit": dataset.commit}
        )
        for q in dataset.questions:
            client.create_dataset_item(
                dataset_name=dataset.label,
                id=f"{dataset.label}-{q.id}",
                input={"question": q.question, "history": list(q.history)},
                expected_output={"expected_files": list(q.expected_files)},
                metadata={"category": q.category},
            )
    except Exception as exc:  # the local report stays the source of truth
        print(f"Langfuse dataset sync skipped: {exc}", file=sys.stderr)
    comment = f"eval run {run}"
    for r in results:
        if not r.trace_id:
            continue
        if r.answerable:
            langfuse.score(r.trace_id, "eval_retrieval_hit", float(hit(r)), comment)
        langfuse.score(r.trace_id, "eval_valid_citations", float(r.valid_citations), comment)
        if r.faithfulness is not None:
            langfuse.score(r.trace_id, "eval_faithfulness", r.faithfulness, comment)
    langfuse.flush()


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m codecompass.eval")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--fail-under", type=float, default=None, help="gate on retrieval hit-rate")
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="dry run before the author verified expected files (report name is marked)",
    )
    args = parser.parse_args(argv)
    configure_logging()
    settings = get_settings()
    try:
        dataset = load(args.dataset, allow_unverified=args.allow_unverified)
    except DatasetError as exc:
        print(f"Dataset error: {exc}", file=sys.stderr)
        return 2

    models = LiteLLMModelFactory(settings)
    if (state := await models.check()) != "ok":
        print(f"LLM provider check: {state}. Set the API key in .env first.", file=sys.stderr)
        return 2
    db = Database(settings.database_url)
    langfuse = LangfuseClient(settings)
    prompts = PromptRegistry()
    prompts.sync(langfuse.client)
    ingestion = IngestionService(db, models, settings, langfuse)
    chat = ChatService(db, models, settings, langfuse, prompts, Guardrails(models))
    try:
        codebase = await ensure_ingested(db, ingestion, dataset)
        check_expected_files(dataset, await indexed_paths(db, codebase.active_ingestion_id))
        results: list[QuestionResult] = []
        for q in dataset.questions:
            print(f"  {q.id}  {q.question}", flush=True)
            results.append(await ask(db, chat, codebase, q))
        await score_faithfulness(results, models.chat("judge"))
        summary = summarise(results)
        label = dataset.label + ("-UNVERIFIED" if args.allow_unverified else "")
        report = write(
            args.dataset.parent.parent / "reports", label, dataset.commit, summary, results
        )
        record_in_langfuse(langfuse, dataset, results, datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    except DatasetError as exc:
        print(f"Dataset error: {exc}", file=sys.stderr)
        return 2
    finally:
        await ingestion.shutdown()
        await db.dispose()

    width = max(len(k) for k in summary)
    for key, value in summary.items():
        print(f"{key.ljust(width)}  {value}")
    print(f"\nReport: {report}")
    return 0 if passes(summary, args.fail_under) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
