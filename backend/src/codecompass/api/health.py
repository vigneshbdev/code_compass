"""GET /api/health (NFR-007, contracts/http-api.md "Health", task T026)."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()

DEGRADING = {"missing", "invalid", "unreachable"}


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    llm: Literal["ok", "missing", "invalid", "unreachable"]
    database: Literal["ok", "unreachable"]
    langfuse: Literal["ok", "unreachable", "disabled"]
    llm_help_url: str
    langfuse_ui_url: str
    version: str


def _version() -> str:
    try:
        return version("codecompass")
    except PackageNotFoundError:
        return "0.0.0"


@router.get("/health", response_model=Health)
async def health(request: Request) -> Health:
    state = request.app.state
    # The LLM probe costs a provider call, so it runs at startup only. DB and Langfuse are cheap.
    llm = state.llm_status
    database = await state.db.check()
    langfuse = await state.langfuse.check()
    degraded = {llm, database, langfuse} & DEGRADING
    return Health(
        status="degraded" if degraded else "ok",
        llm=llm,
        database=database,
        langfuse=langfuse,
        llm_help_url=state.settings.llm_help_url,
        langfuse_ui_url=state.settings.langfuse_ui_url,
        version=_version(),
    )
