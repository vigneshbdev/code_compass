"""FR-001 / FR-005: fetching a public GitHub repo, offline via httpx.MockTransport (task T040)."""

from __future__ import annotations

import io
import os
import tarfile
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from codecompass.api.errors import AppError, ErrorCode
from codecompass.ingestion.sources import FetchResult, GithubRef, fetch_github
from tests.fakes.settings import make_settings

API = "https://gh.test"
SHA = "a" * 40


def _tarball(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(f"o-r-{SHA[:7]}/{name}")
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def _github(
    *,
    repo_status: int = 200,
    tarball: bytes | None = None,
    seen: list[str] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    tarball = tarball if tarball is not None else _tarball({"main.py": b"print(1)\n"})

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        path = request.url.path
        if path == "/repos/o/r":
            if repo_status != 200:
                return httpx.Response(repo_status, json={"message": "nope"})
            return httpx.Response(
                200, json={"default_branch": "main", "size": 10, "private": False}
            )
        if path.startswith("/repos/o/r/commits/"):
            return httpx.Response(200, json={"sha": SHA})
        if path == f"/repos/o/r/tarball/{SHA}":
            return httpx.Response(200, content=tarball)
        return httpx.Response(404)

    return handler


async def _fetch(
    handler: Callable[[httpx.Request], httpx.Response],
    tmp_path: Path,
    ref: str | None = None,
    **settings: object,
) -> FetchResult:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        return await fetch_github(
            GithubRef("o", "r", ref),
            settings=make_settings(github_api_base=API, **settings),
            dest=tmp_path / "work",
            http=http,
        )


async def test_fr001_downloads_and_extracts_default_branch(tmp_path: Path) -> None:
    seen: list[str] = []
    result = await _fetch(_github(seen=seen), tmp_path)
    assert result.commit_sha == SHA
    assert (result.root / "main.py").read_text() == "print(1)\n"
    assert all(url.startswith(API) for url in seen)  # base URL comes from settings
    assert f"{API}/repos/o/r/commits/main" in seen


async def test_fr001_tree_ref_resolves_commit(tmp_path: Path) -> None:
    seen: list[str] = []
    await _fetch(_github(seen=seen), tmp_path, ref="v1.2.3")
    assert f"{API}/repos/o/r/commits/v1.2.3" in seen


async def test_fr001_missing_or_private_repo(tmp_path: Path) -> None:
    with pytest.raises(AppError) as info:
        await _fetch(_github(repo_status=404), tmp_path)
    assert info.value.code is ErrorCode.REPO_NOT_FOUND


@pytest.mark.parametrize("status", [403, 429])
async def test_fr001_rate_limited(tmp_path: Path, status: int) -> None:
    with pytest.raises(AppError) as info:
        await _fetch(_github(repo_status=status), tmp_path)
    assert info.value.code is ErrorCode.GITHUB_RATE_LIMITED
    assert "GITHUB_TOKEN" in info.value.message


async def test_fr005_download_cap_aborts_while_streaming(tmp_path: Path) -> None:
    big = _tarball({"blob.bin": os.urandom(300_000)})  # incompressible, so really 300 KB
    with pytest.raises(AppError) as info:
        await _fetch(_github(tarball=big), tmp_path, max_download_bytes=1_000)
    assert info.value.code is ErrorCode.REPO_TOO_LARGE
