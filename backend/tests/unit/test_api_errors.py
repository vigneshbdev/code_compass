"""contracts/http-api.md error shape and codes (task T013)."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from codecompass.api.errors import AppError, ErrorCode, install_error_handlers

CONTRACT_STATUS = {
    "invalid_github_url": 422,
    "repo_not_found": 404,
    "github_rate_limited": 503,
    "repo_too_large": 413,
    "invalid_archive": 422,
    "no_supported_files": 422,
    "codebase_not_ready": 409,
    "llm_unavailable": 503,
    "trace_unavailable": 503,
    "not_found": 404,
}


def test_error_codes_match_contract_table() -> None:
    assert {c.value: c.status for c in ErrorCode} == CONTRACT_STATUS


@pytest.mark.parametrize("code", list(ErrorCode))
async def test_app_error_renders_contract_shape(code: ErrorCode) -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise AppError(code, "Something user-facing went wrong.")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/boom")
    assert response.status_code == code.status
    assert response.json() == {
        "error": {"code": code.value, "message": "Something user-facing went wrong."}
    }


async def test_unhandled_exception_does_not_leak_details() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/crash")
    async def crash() -> None:
        raise RuntimeError("internal detail with secret sk-abc")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/crash")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "sk-abc" not in response.text


async def _call(app: FastAPI, method: str, path: str, **kwargs: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)  # type: ignore[arg-type]


async def test_framework_404_uses_contract_shape() -> None:
    app = FastAPI()
    install_error_handlers(app)
    response = await _call(app, "GET", "/api/nope")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not found."}}


async def test_framework_405_uses_contract_shape() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/only-get")
    async def only_get() -> None:
        return None

    response = await _call(app, "POST", "/only-get")
    assert response.status_code == 405
    assert set(response.json()) == {"error"}
    assert response.json()["error"]["code"] == "http_error"


class Body(BaseModel):
    url: str


async def test_validation_error_uses_contract_shape() -> None:
    app = FastAPI()
    install_error_handlers(app)

    @app.post("/things")
    async def things(body: Body) -> None:
        return None

    response = await _call(app, "POST", "/things", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "url" in response.json()["error"]["message"]
