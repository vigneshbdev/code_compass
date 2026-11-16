"""Error codes and the error response shape from contracts/http-api.md (task T025)."""

from __future__ import annotations

import logging
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorCode(Enum):
    INVALID_GITHUB_URL = ("invalid_github_url", 422)
    REPO_NOT_FOUND = ("repo_not_found", 404)
    GITHUB_RATE_LIMITED = ("github_rate_limited", 503)
    REPO_TOO_LARGE = ("repo_too_large", 413)
    INVALID_ARCHIVE = ("invalid_archive", 422)
    NO_SUPPORTED_FILES = ("no_supported_files", 422)
    CODEBASE_NOT_READY = ("codebase_not_ready", 409)
    LLM_UNAVAILABLE = ("llm_unavailable", 503)
    TRACE_UNAVAILABLE = ("trace_unavailable", 503)
    NOT_FOUND = ("not_found", 404)

    def __init__(self, code: str, status: int) -> None:
        self.code = code
        self.status = status

    @property
    def value(self) -> str:  # type: ignore[override]  # the wire value is the code string
        return self.code


class AppError(Exception):
    """An error with a user-facing message. Never put secrets or internals in `message`."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def error_body(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.code.status, content=error_body(exc.code.value, exc.message)
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Framework errors (unknown route, wrong method) use the contract shape too.
        if exc.status_code == 404:
            return JSONResponse(
                status_code=404, content=error_body(ErrorCode.NOT_FOUND.value, "Not found.")
            )
        message = str(exc.detail) if exc.detail else "Request failed."
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body("http_error", message),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = ", ".join(".".join(str(p) for p in err["loc"][1:]) for err in exc.errors())
        message = f"Invalid request: {fields}." if fields else "Invalid request."
        return JSONResponse(status_code=422, content=error_body("invalid_request", message))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=error_body("internal_error", "Something went wrong. Check the server logs."),
        )
