"""Language breakdown for the overview (FR-020, task T149)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from codecompass.chunking import detect_language


def languages(files: dict[str, str]) -> list[dict[str, Any]]:
    """[{language, files, lines}] sorted by file count, then lines."""
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for path, text in files.items():
        row = counts[detect_language(path)]
        row[0] += 1
        row[1] += len(text.splitlines())
    rows = [{"language": lang, "files": f, "lines": n} for lang, (f, n) in counts.items()]
    return sorted(rows, key=lambda r: (-r["files"], -r["lines"], r["language"]))
