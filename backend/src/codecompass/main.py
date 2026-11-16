"""Application factory (task T026).

Startup never exits on a bad LLM key (NFR-007): it logs a prominent message, and the UI shows
a banner from /api/health. Langfuse failures never block startup (research R10).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from codecompass.api import chat, codebases, conversations, health, messages
from codecompass.api.errors import AppError, ErrorCode, install_error_handlers
from codecompass.chat.service import ChatService
from codecompass.config import Settings, get_settings
from codecompass.guardrails.rails import Guardrails
from codecompass.ingestion.pipeline import IngestionService
from codecompass.llm.factory import LiteLLMModelFactory, ModelFactory
from codecompass.observability.langfuse_client import LangfuseClient
from codecompass.observability.logging import configure_logging
from codecompass.observability.prompt_sync import PromptRegistry
from codecompass.storage.db import Database

logger = logging.getLogger(__name__)

KEY_HELP = "Set the provider API key in .env (see the README's API key section)."


def create_app(
    settings: Settings | None = None,
    model_factory: ModelFactory | None = None,
    langfuse: LangfuseClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.models = model_factory or LiteLLMModelFactory(settings)
        app.state.langfuse = langfuse or LangfuseClient(settings)
        app.state.db = Database(settings.database_url)
        app.state.prompts = PromptRegistry()

        app.state.llm_status = await app.state.models.check()
        if app.state.llm_status != "ok":
            logger.error(
                "LLM provider check: %s. Chat will not work. %s", app.state.llm_status, KEY_HELP
            )
        if await app.state.db.check() != "ok":
            logger.error("Database unreachable at startup")
        app.state.ingestion = IngestionService(
            app.state.db, app.state.models, settings, app.state.langfuse
        )
        if await app.state.db.check() == "ok":
            await app.state.ingestion.recover_on_startup()
        app.state.guardrails = Guardrails(app.state.models)
        app.state.chat = ChatService(
            app.state.db,
            app.state.models,
            settings,
            app.state.langfuse,
            app.state.prompts,
            app.state.guardrails,
        )
        langfuse_state = await app.state.langfuse.check()
        if langfuse_state == "unreachable":
            logger.warning("Langfuse unreachable at startup; chat works, traces will be missing")
        app.state.prompts.sync(app.state.langfuse.client)
        try:
            yield
        finally:
            await app.state.ingestion.shutdown()
            app.state.langfuse.flush()
            await app.state.db.dispose()

    app = FastAPI(
        title="CodeCompass",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    install_error_handlers(app)

    api = APIRouter(prefix="/api")
    api.include_router(health.router)
    api.include_router(codebases.router)
    api.include_router(conversations.router)
    api.include_router(chat.router)
    api.include_router(messages.router)
    app.include_router(api)

    _mount_spa(app, settings.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve the built SPA; any non-/api path falls back to index.html for client routing."""
    index = static_dir / "index.html"
    if not index.exists():
        return
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:  # sync: FastAPI runs it in a thread (file I/O)
        if path == "api" or path.startswith("api/"):
            raise AppError(ErrorCode.NOT_FOUND, "Not found.")  # never answer the API with HTML
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(static_dir.resolve()):
            return FileResponse(candidate)
        return FileResponse(index)


def app_factory() -> FastAPI:
    """Entry point for `uvicorn --factory codecompass.main:app_factory` (Dockerfile)."""
    configure_logging()
    return create_app()
