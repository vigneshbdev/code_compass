"""FR-003 / FR-004: what is indexed and why everything else is skipped (task T035)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codecompass.ingestion.filters import select_files
from tests.fakes.settings import make_settings
from tests.fixtures import repos


@pytest.fixture
def result(tmp_path: Path):  # type: ignore[no-untyped-def]
    root = repos.mini_python_repo(tmp_path)
    (root / "keys").mkdir()
    (root / "keys" / "server.pem").write_text("fake")
    return select_files(root, make_settings(max_file_bytes=524_288))


def test_fr003_each_skip_reason(result) -> None:  # type: ignore[no-untyped-def]
    reasons = {s.path: s.reason for s in result.skipped}
    assert reasons["generated"] == "gitignored"  # whole directory skipped once
    assert reasons["node_modules"] == "denylisted_dir"  # whole directory skipped once
    assert reasons["poetry.lock"] == "lockfile"
    assert reasons["logo.png"] == "binary"
    assert reasons["big.min.js"] == "too_large"  # size cap catches minified bundles (R13)
    assert reasons["latin1.txt"] == "non_utf8"
    assert reasons["keys/server.pem"] == "private_key_file"


def test_fr003_source_and_docs_are_kept(result) -> None:  # type: ignore[no-untyped-def]
    kept = {f.path for f in result.kept}
    assert {
        "app/main.py",
        "app/api/users.py",
        "app/core/config.py",
        "README.md",
        "pyproject.toml",
        "requirements.txt",
    } <= kept
    assert not any(p.startswith(("node_modules", "generated/")) for p in kept)


def test_fr003_kept_files_carry_decoded_text(result) -> None:  # type: ignore[no-untyped-def]
    main = next(f for f in result.kept if f.path == "app/main.py")
    assert "FastAPI" in main.text
    assert main.size == len(main.text.encode())


def test_fr003_utf8_bom_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "bom.py").write_bytes("﻿x = 1\n".encode())
    result = select_files(tmp_path, make_settings())
    assert [f.text for f in result.kept] == ["x = 1\n"]


def test_fr003_nested_gitignore(tmp_path: Path) -> None:
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / ".gitignore").write_text("secret_gen.py\n")
    (tmp_path / "pkg" / "secret_gen.py").write_text("x = 1\n")
    (tmp_path / "pkg" / "keep.py").write_text("y = 2\n")
    result = select_files(tmp_path, make_settings())
    assert {f.path for f in result.kept} == {"pkg/keep.py", "pkg/.gitignore"}
    assert {s.path: s.reason for s in result.skipped}["pkg/secret_gen.py"] == "gitignored"


def test_fr003_root_gitignore_applies_in_subdirectories(tmp_path: Path) -> None:
    """Spec-reviewer finding: root rules must be inherited by every subfolder."""
    (tmp_path / ".gitignore").write_text("*.log\nsecrets/\n")
    (tmp_path / "src" / "deep").mkdir(parents=True)
    (tmp_path / "src" / "app.py").write_text("x = 1\n")
    (tmp_path / "src" / "debug.log").write_text("noise\n")
    (tmp_path / "src" / "deep" / "trace.log").write_text("noise\n")
    (tmp_path / "src" / "secrets").mkdir()
    (tmp_path / "src" / "secrets" / "k.py").write_text("k = 1\n")
    result = select_files(tmp_path, make_settings())
    reasons = {s.path: s.reason for s in result.skipped}
    assert reasons["src/debug.log"] == "gitignored"
    assert reasons["src/deep/trace.log"] == "gitignored"
    assert reasons["src/secrets"] == "gitignored"
    assert {f.path for f in result.kept} == {".gitignore", "src/app.py"}
