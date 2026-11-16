"""Choose which files to index and record why the rest are skipped (FR-003, FR-004, T046).

Order of checks: deny-listed directories → .gitignore → private key files → lockfiles →
size cap → binary (NUL byte) → UTF-8 decode. Minified/generated bundles are caught by the size
cap (research R13). Every skip carries one of the reasons in data-model.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

from codecompass.config import Settings

DENY_DIRS = {
    "node_modules",
    ".git",
    "dist",
    "build",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    "coverage",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".next",
    ".tox",
    ".idea",
    ".vscode",
    "target",
    "bower_components",
}
LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "Cargo.lock",
    "composer.lock",
    "Gemfile.lock",
    "go.sum",
}
PRIVATE_KEY_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
PRIVATE_KEY_PREFIXES = ("id_rsa", "id_dsa", "id_ecdsa", "id_ed25519")
BINARY_SNIFF_BYTES = 8192


@dataclass(frozen=True)
class Skip:
    path: str
    reason: str


@dataclass(frozen=True)
class SourceFile:
    path: str  # POSIX, relative to the repo root
    text: str
    size: int


@dataclass
class FilterResult:
    kept: list[SourceFile] = field(default_factory=list)
    skipped: list[Skip] = field(default_factory=list)


def _is_private_key(name: str) -> bool:
    lower = name.lower()
    if lower.endswith(".pub"):
        return False
    return Path(lower).suffix in PRIVATE_KEY_SUFFIXES or lower.startswith(PRIVATE_KEY_PREFIXES)


def _load_gitignore(directory: Path) -> pathspec.GitIgnoreSpec | None:
    path = directory / ".gitignore"
    if not path.is_file():
        return None
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return None
    return pathspec.GitIgnoreSpec.from_lines(lines)  # git's own .gitignore semantics


def _ignored(rel: str, is_dir: bool, specs: list[tuple[str, pathspec.GitIgnoreSpec]]) -> bool:
    """`specs` holds (directory prefix, spec) for each .gitignore from the root down."""
    for prefix, spec in specs:
        if prefix and not rel.startswith(prefix + "/"):
            continue
        local = rel[len(prefix) + 1 :] if prefix else rel
        if spec.match_file(local + "/" if is_dir else local):
            return True
    return False


def _classify(path: Path, rel: str, settings: Settings) -> tuple[SourceFile | None, str | None]:
    name = path.name
    if _is_private_key(name):
        return None, "private_key_file"
    if name in LOCKFILES:
        return None, "lockfile"
    size = path.stat().st_size
    if size > settings.max_file_bytes:
        return None, "too_large"
    data = path.read_bytes()
    if b"\0" in data[:BINARY_SNIFF_BYTES]:
        return None, "binary"
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "non_utf8"
    return SourceFile(rel, text, len(text.encode())), None


def select_files(root: Path, settings: Settings) -> FilterResult:
    result = FilterResult()
    root = root.resolve()
    specs_by_dir: dict[str, list[tuple[str, pathspec.GitIgnoreSpec]]] = {}

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        rel_dir = current.relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        # Inherit every .gitignore from the root down. The root is keyed "" (not "."), so a
        # top-level folder's parent must map to "" too.
        parent = rel_dir.rpartition("/")[0]
        specs = list(specs_by_dir.get(parent, [])) if rel_dir else []
        own = _load_gitignore(current)
        if own is not None:
            specs.append((rel_dir, own))
        specs_by_dir[rel_dir] = specs

        kept_dirs: list[str] = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if (current / d).is_symlink():
                result.skipped.append(Skip(rel, "symlink"))
            elif d in DENY_DIRS:
                result.skipped.append(Skip(rel, "denylisted_dir"))
            elif _ignored(rel, True, specs):
                result.skipped.append(Skip(rel, "gitignored"))
            else:
                kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for f in sorted(filenames):
            path = current / f
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if path.is_symlink():
                result.skipped.append(Skip(rel, "symlink"))
                continue
            if _ignored(rel, False, specs):
                result.skipped.append(Skip(rel, "gitignored"))
                continue
            source, reason = _classify(path, rel, settings)
            if source is not None:
                result.kept.append(source)
            elif reason is not None:
                result.skipped.append(Skip(rel, reason))
    return result
