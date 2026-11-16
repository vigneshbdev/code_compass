"""Where code comes from: a public GitHub repo or an uploaded zip (FR-001, FR-002, T044, T045).

Archives are untrusted input. Extraction skips absolute and `..` paths and symlinks, caps the
entry count and the total uncompressed size (zip-bomb guard), and never writes outside its
destination. The app never reads arbitrary host paths (FR-002).
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import re
import shutil
import stat
import tarfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import IO

import httpx

from codecompass.api.errors import AppError, ErrorCode
from codecompass.config import Settings
from codecompass.ingestion.filters import Skip

GITHUB_URL = re.compile(
    r"^https://github\.com/"  # literal-ok: validates user input; API calls use GITHUB_API_BASE
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]{0,38}))/"
    r"(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?(?:/tree/(?P<ref>[^\s]+?))?/?$"
)
COPY_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class GithubRef:
    owner: str
    repo: str
    ref: str | None


@dataclass
class ExtractResult:
    root: Path
    skipped: list[Skip] = field(default_factory=list)


@dataclass
class FetchResult(ExtractResult):
    commit_sha: str = ""


def parse_github_url(url: str) -> GithubRef:
    match = GITHUB_URL.match(url.strip())
    if not match or match.group("repo") in {"", ".", ".."}:
        raise AppError(
            ErrorCode.INVALID_GITHUB_URL,
            "Enter a public GitHub repository URL like "
            "https://github.com/owner/repo.",  # literal-ok: example shown to the user
        )
    return GithubRef(match.group("owner"), match.group("repo"), match.group("ref"))


# ── Safe extraction ────────────────────────────────────────────────────────────────────────


def _unsafe(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return path.is_absolute() or bool(re.match(r"^[A-Za-z]:", normalized)) or ".." in path.parts


class _Budget:
    def __init__(self, settings: Settings) -> None:
        self.remaining = settings.max_uncompressed_bytes

    def consume(self, n: int) -> None:
        self.remaining -= n
        if self.remaining < 0:
            raise AppError(
                ErrorCode.INVALID_ARCHIVE,
                "The archive expands to more than the allowed size and was rejected.",
            )


def _write(src: IO[bytes], target: Path, dest: Path, budget: _Budget) -> None:
    target = target.resolve()
    if not target.is_relative_to(dest):
        raise AppError(ErrorCode.INVALID_ARCHIVE, "The archive contains an unsafe path.")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as out:
        while chunk := src.read(COPY_CHUNK):
            budget.consume(len(chunk))
            out.write(chunk)


def _unwrap(dest: Path) -> Path:
    """GitHub tarballs and most zips have one top-level folder; index its contents."""
    entries = list(dest.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest


def _check_entry_count(count: int, settings: Settings) -> None:
    if count > settings.max_archive_entries:
        raise AppError(
            ErrorCode.INVALID_ARCHIVE,
            f"The archive has {count} entries; the limit is {settings.max_archive_entries}.",
        )


def safe_extract_zip(data: bytes | Path, dest: Path, settings: Settings) -> ExtractResult:
    with contextlib.ExitStack() as stack:
        source: IO[bytes] = (
            io.BytesIO(data) if isinstance(data, bytes) else stack.enter_context(data.open("rb"))
        )
        return _extract_zip(source, dest, settings)


def _extract_zip(source: IO[bytes], dest: Path, settings: Settings) -> ExtractResult:
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile:
        raise AppError(ErrorCode.INVALID_ARCHIVE, "The upload is not a valid .zip file.") from None
    with archive:
        infos = archive.infolist()
        _check_entry_count(len(infos), settings)
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest.resolve()
        budget = _Budget(settings)
        result = ExtractResult(dest)
        for info in infos:
            if info.is_dir():
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                result.skipped.append(Skip(info.filename, "symlink"))
            elif _unsafe(info.filename):
                result.skipped.append(Skip(info.filename, "unsafe_path"))
            else:
                with archive.open(info) as src:
                    _write(src, dest / info.filename, dest, budget)
        result.root = _unwrap(dest)
        return result


def safe_extract_tar(archive_path: Path, dest: Path, settings: Settings) -> ExtractResult:
    try:
        archive = tarfile.open(archive_path, "r:*")  # noqa: SIM115 - closed by the `with` below
    except tarfile.TarError:
        raise AppError(
            ErrorCode.INVALID_ARCHIVE, "The downloaded archive is not readable."
        ) from None
    with archive:
        members = archive.getmembers()
        _check_entry_count(len(members), settings)
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest.resolve()
        budget = _Budget(settings)
        result = ExtractResult(dest)
        for member in members:
            if member.isdir():
                continue
            if member.issym() or member.islnk():
                result.skipped.append(Skip(member.name, "symlink"))
            elif _unsafe(member.name):
                result.skipped.append(Skip(member.name, "unsafe_path"))
            elif member.isfile():
                src = archive.extractfile(member)
                if src is not None:
                    with src:
                        _write(src, dest / member.name, dest, budget)
        result.root = _unwrap(dest)
        return result


# ── GitHub ─────────────────────────────────────────────────────────────────────────────────

NOT_FOUND_MESSAGE = "Repository not found. It may be private, misspelt or deleted."
RATE_LIMIT_MESSAGE = "GitHub rate limit reached. Try again later, or set GITHUB_TOKEN in .env."


def _headers(settings: Settings) -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token.get_secret_value()}"
    return headers


def _raise_for_github(response: httpx.Response, not_found: str = NOT_FOUND_MESSAGE) -> None:
    if response.status_code == 404:
        raise AppError(ErrorCode.REPO_NOT_FOUND, not_found)
    if response.status_code in {403, 429}:
        raise AppError(ErrorCode.GITHUB_RATE_LIMITED, RATE_LIMIT_MESSAGE)
    if response.status_code >= 400:
        raise AppError(
            ErrorCode.GITHUB_RATE_LIMITED,
            f"GitHub returned an error ({response.status_code}). Try again later.",
        )


async def fetch_github(
    ref: GithubRef, *, settings: Settings, dest: Path, http: httpx.AsyncClient
) -> FetchResult:
    base = f"{settings.github_api_base.rstrip('/')}/repos/{ref.owner}/{ref.repo}"
    headers = _headers(settings)

    meta = await http.get(base, headers=headers)
    _raise_for_github(meta)
    info = meta.json()
    if info.get("private"):
        raise AppError(ErrorCode.REPO_NOT_FOUND, "Private repositories are not supported.")

    wanted = ref.ref or str(info["default_branch"])
    commit = await http.get(f"{base}/commits/{wanted}", headers=headers)
    _raise_for_github(commit, f"Branch, tag or commit '{wanted}' was not found.")
    sha = str(commit.json()["sha"])

    archive_path = dest / "repo.tar.gz"
    downloaded = 0
    # File I/O runs in worker threads so a large download never blocks the event loop.
    await asyncio.to_thread(dest.mkdir, parents=True, exist_ok=True)
    out = await asyncio.to_thread(archive_path.open, "wb")
    try:
        async with http.stream(
            "GET", f"{base}/tarball/{sha}", headers=headers, follow_redirects=True
        ) as response:
            _raise_for_github(response)
            async for chunk in response.aiter_bytes(COPY_CHUNK):
                downloaded += len(chunk)
                if downloaded > settings.max_download_bytes:
                    raise AppError(
                        ErrorCode.REPO_TOO_LARGE,
                        f"The repository archive is larger than the "
                        f"{settings.max_download_bytes // 1_000_000} MB download limit.",
                    )
                await asyncio.to_thread(out.write, chunk)
    finally:
        await asyncio.to_thread(out.close)

    try:
        extracted = await asyncio.to_thread(safe_extract_tar, archive_path, dest / "src", settings)
    finally:
        await asyncio.to_thread(archive_path.unlink, missing_ok=True)
    return FetchResult(root=extracted.root, skipped=extracted.skipped, commit_sha=sha)


def cleanup(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
