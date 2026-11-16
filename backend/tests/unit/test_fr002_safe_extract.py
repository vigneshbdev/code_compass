"""FR-002 + edge cases: archive extraction is safe (task T034)."""

from __future__ import annotations

import io
import stat
import tarfile
import zipfile
from pathlib import Path

import pytest

from codecompass.api.errors import AppError, ErrorCode
from codecompass.ingestion.sources import safe_extract_tar, safe_extract_zip
from tests.fakes.settings import make_settings


def _zip(entries: dict[str, bytes], symlinks: dict[str, str] | None = None) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
        for name, target in (symlinks or {}).items():
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(info, target)
    return buffer.getvalue()


def test_fr002_extracts_normal_entries_and_skips_unsafe_ones(tmp_path: Path) -> None:
    data = _zip(
        {
            "proj/app.py": b"print('hi')\n",
            "../evil.py": b"owned",
            "/abs/evil.py": b"owned",
            "proj/../../escape.py": b"owned",
        },
        symlinks={"proj/link": "/etc/passwd"},
    )
    result = safe_extract_zip(data, tmp_path / "out", make_settings())
    assert (result.root / "app.py").read_text() == "print('hi')\n"  # single top folder unwrapped
    reasons = {s.path: s.reason for s in result.skipped}
    assert reasons["../evil.py"] == "unsafe_path"
    assert reasons["/abs/evil.py"] == "unsafe_path"
    assert reasons["proj/../../escape.py"] == "unsafe_path"
    assert reasons["proj/link"] == "symlink"
    assert not (tmp_path / "evil.py").exists()
    assert not (tmp_path / "escape.py").exists()
    assert not any(p.is_symlink() for p in (tmp_path / "out").rglob("*"))


def test_fr002_zip_bomb_is_rejected(tmp_path: Path) -> None:
    data = _zip({"big.txt": b"0" * 2_000_000})
    with pytest.raises(AppError) as info:
        safe_extract_zip(data, tmp_path / "out", make_settings(max_uncompressed_bytes=1_000_000))
    assert info.value.code is ErrorCode.INVALID_ARCHIVE


def test_fr002_too_many_entries_is_rejected(tmp_path: Path) -> None:
    data = _zip({f"f{i}.txt": b"x" for i in range(20)})
    with pytest.raises(AppError) as info:
        safe_extract_zip(data, tmp_path / "out", make_settings(max_archive_entries=10))
    assert info.value.code is ErrorCode.INVALID_ARCHIVE


def test_fr002_non_zip_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AppError) as info:
        safe_extract_zip(b"this is not a zip", tmp_path / "out", make_settings())
    assert info.value.code is ErrorCode.INVALID_ARCHIVE


def _tar(entries: dict[str, bytes], symlinks: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
        for name, target in symlinks.items():
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tf.addfile(info)
    return buffer.getvalue()


def test_fr002_tarball_gets_the_same_checks(tmp_path: Path) -> None:
    data = _tar(
        {"owner-repo-abc123/src/main.py": b"x = 1\n", "owner-repo-abc123/../../evil": b"owned"},
        symlinks={"owner-repo-abc123/link": "/etc/passwd"},
    )
    archive = tmp_path / "repo.tar.gz"
    archive.write_bytes(data)
    result = safe_extract_tar(archive, tmp_path / "out", make_settings())
    assert (result.root / "src" / "main.py").read_text() == "x = 1\n"
    reasons = {s.reason for s in result.skipped}
    assert reasons == {"unsafe_path", "symlink"}
    assert not (tmp_path / "evil").exists()
