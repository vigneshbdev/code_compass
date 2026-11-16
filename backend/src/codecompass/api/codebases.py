"""Codebase endpoints (FR-001…FR-007, contracts/http-api.md "Codebases", task T055)."""

from __future__ import annotations

import io
import uuid
import zipfile
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from codecompass.api.errors import AppError, ErrorCode
from codecompass.api.schemas import CodebaseList, CodebaseOut, FileOut, GithubIn
from codecompass.config import Settings
from codecompass.ingestion.pipeline import IngestionService
from codecompass.storage.db import get_session
from codecompass.storage.models import Codebase, Ingestion
from codecompass.storage.repositories import chunks as chunk_repo
from codecompass.storage.repositories import codebases as codebase_repo
from codecompass.storage.repositories import conversations as conversation_repo
from codecompass.storage.repositories import ingestions as ingestion_repo

router = APIRouter(prefix="/codebases", tags=["codebases"])
Session = Annotated[AsyncSession, Depends(get_session)]
UPLOAD_CHUNK = 1024 * 1024


def _service(request: Request) -> IngestionService:
    service: IngestionService = request.app.state.ingestion
    return service


def _require_llm(request: Request) -> None:
    """NFR-007: indexing needs embeddings, so refuse clearly instead of failing later."""
    if request.app.state.llm_status != "ok":
        raise AppError(
            ErrorCode.LLM_UNAVAILABLE,
            "Indexing needs a working LLM API key (embeddings). "
            "Set it in .env and restart; see the README's API key section.",
        )


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def _out(session: AsyncSession, codebase: Codebase, settings: Settings) -> CodebaseOut:
    active = (
        await session.get(Ingestion, codebase.active_ingestion_id)
        if codebase.active_ingestion_id
        else None
    )
    latest = await ingestion_repo.latest(session, codebase.id)
    return CodebaseOut.build(codebase, active, latest, settings)


async def _out_by_id(request: Request, codebase_id: uuid.UUID) -> CodebaseOut:
    async with request.app.state.db.sessions() as session:
        codebase = await codebase_repo.get(session, codebase_id)
        return await _out(session, codebase, _settings(request))


@router.post("/github", status_code=202, response_model=CodebaseOut)
async def create_from_github(body: GithubIn, request: Request) -> CodebaseOut:
    _require_llm(request)
    codebase_id = await _service(request).submit_github(body.url, body.ref)
    return await _out_by_id(request, codebase_id)


@router.post("/zip", status_code=202, response_model=CodebaseOut)
async def create_from_zip(file: UploadFile, request: Request) -> CodebaseOut:
    _require_llm(request)
    limit = _settings(request).max_upload_bytes
    data = bytearray()
    while chunk := await file.read(UPLOAD_CHUNK):
        data.extend(chunk)
        if len(data) > limit:
            raise AppError(
                ErrorCode.REPO_TOO_LARGE,
                f"The upload is larger than the {limit // 1_000_000} MB limit.",
            )
    if not zipfile.is_zipfile(io.BytesIO(bytes(data))):
        raise AppError(ErrorCode.INVALID_ARCHIVE, "The upload is not a valid .zip file.")
    codebase_id = await _service(request).submit_zip(file.filename or "upload.zip", bytes(data))
    return await _out_by_id(request, codebase_id)


@router.get("", response_model=CodebaseList)
async def list_codebases(session: Session, request: Request) -> CodebaseList:
    settings = _settings(request)
    return CodebaseList(
        items=[await _out(session, c, settings) for c in await codebase_repo.list_all(session)]
    )


@router.get("/{codebase_id}", response_model=CodebaseOut)
async def get_codebase(codebase_id: str, session: Session, request: Request) -> CodebaseOut:
    codebase = await codebase_repo.get(session, codebase_id)
    return await _out(session, codebase, _settings(request))


@router.post("/{codebase_id}/reingest", status_code=202, response_model=CodebaseOut)
async def reingest(codebase_id: str, request: Request) -> CodebaseOut:
    async with request.app.state.db.sessions() as session:
        codebase = await codebase_repo.get(session, codebase_id)
    _require_llm(request)
    await _service(request).reingest(codebase.id)
    return await _out_by_id(request, codebase.id)


@router.delete("/{codebase_id}", status_code=204)
async def delete_codebase(codebase_id: str, session: Session, request: Request) -> Response:
    codebase = await codebase_repo.get(session, codebase_id)
    trace_ids = await conversation_repo.trace_ids_for_codebase(session, codebase.id)
    await codebase_repo.delete_codebase(session, codebase)
    await session.commit()
    _service(request).forget_upload(codebase.id)
    request.app.state.langfuse.delete_traces(trace_ids)  # best effort (FR-007)
    return Response(status_code=204)


@router.get("/{codebase_id}/overview")
async def get_overview(codebase_id: str, session: Session) -> dict[str, Any]:
    """Languages, dependencies and starter questions (FR-020, FR-021)."""
    codebase = await codebase_repo.get(session, codebase_id)
    active = (
        await session.get(Ingestion, codebase.active_ingestion_id)
        if codebase.active_ingestion_id
        else None
    )
    if active is None or active.overview is None:
        raise AppError(ErrorCode.CODEBASE_NOT_READY, "The overview is available after indexing.")
    return active.overview


@router.get("/{codebase_id}/files", response_model=FileOut)
async def get_file(codebase_id: str, path: str, session: Session) -> FileOut:
    """Redacted content of an indexed file (FR-012, FR-030). Never reads the host filesystem."""
    codebase = await codebase_repo.get(session, codebase_id)
    if codebase.active_ingestion_id is None:
        raise AppError(ErrorCode.CODEBASE_NOT_READY, "This codebase is not indexed yet.")
    file = await chunk_repo.file_content(session, codebase.active_ingestion_id, path)
    if file is None:
        raise AppError(ErrorCode.NOT_FOUND, "File not found in this codebase.")
    return FileOut(
        path=file.path,
        language=file.language,
        line_count=file.line_count,
        content=file.content,
        redaction_count=file.redaction_count,
    )
