"""Declared dependencies from manifests (FR-020, task T149).

Reads `pyproject.toml` (PEP 621 and Poetry), `requirements*.txt` and `package.json`. Input is the
*redacted* file content, so tokens embedded in dependency URLs never reach the overview.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from pathlib import PurePosixPath
from typing import Any

logger = logging.getLogger(__name__)

# Options (-r, -e, --index-url) and direct URLs are not package names.
SKIP_PREFIXES = ("-", "git+", "http://", "https://")  # literal-ok: URL prefixes to skip
REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*?)\s*(?:;.*)?$")


def _dep(manifest: str, ecosystem: str, name: str, spec: str, dev: bool) -> dict[str, Any]:
    return {"manifest": manifest, "ecosystem": ecosystem, "name": name, "spec": spec, "dev": dev}


def _pep508(manifest: str, line: str, dev: bool) -> dict[str, Any] | None:
    match = REQUIREMENT.match(line)
    return _dep(manifest, "pypi", match.group(1), match.group(3), dev) if match else None


def _pyproject(path: str, text: str) -> list[dict[str, Any]]:
    data = tomllib.loads(text)
    out: list[dict[str, Any]] = []
    project = data.get("project", {})
    for line in project.get("dependencies", []):
        if (d := _pep508(path, line, False)) is not None:
            out.append(d)
    for group in project.get("optional-dependencies", {}).values():
        out.extend(d for line in group if (d := _pep508(path, line, True)) is not None)
    for group in data.get("dependency-groups", {}).values():
        out.extend(
            d for line in group if isinstance(line, str) and (d := _pep508(path, line, True))
        )
    poetry = data.get("tool", {}).get("poetry", {})
    for name, spec in poetry.get("dependencies", {}).items():
        if name.lower() != "python":
            out.append(_dep(path, "pypi", name, spec if isinstance(spec, str) else "", False))
    for name, spec in poetry.get("group", {}).get("dev", {}).get("dependencies", {}).items():
        out.append(_dep(path, "pypi", name, spec if isinstance(spec, str) else "", True))
    return out


def _requirements(path: str, text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(SKIP_PREFIXES):
            continue
        if (d := _pep508(path, line, False)) is not None:
            out.append(d)
    return out


def _package_json(path: str, text: str) -> list[dict[str, Any]]:
    data = json.loads(text)
    out = [_dep(path, "npm", n, str(s), False) for n, s in data.get("dependencies", {}).items()]
    out += [_dep(path, "npm", n, str(s), True) for n, s in data.get("devDependencies", {}).items()]
    return out


def dependencies(files: dict[str, str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(files):
        name = PurePosixPath(path).name
        try:
            if name == "pyproject.toml":
                out += _pyproject(path, files[path])
            elif name.startswith("requirements") and name.endswith(".txt"):
                out += _requirements(path, files[path])
            elif name == "package.json" and "node_modules" not in path:
                out += _package_json(path, files[path])
        except (ValueError, tomllib.TOMLDecodeError):
            logger.info("unreadable manifest skipped", extra={"data": {"path": path}})
    return out
