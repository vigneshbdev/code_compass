#!/usr/bin/env python3
"""Cross-model code review: a different model (Gemini) reviews code written by Claude.

Constitution, Quality Gate 3: "No model grades its own homework."

Usage:
    python scripts/cross-review.py              # review staged changes
    python scripts/cross-review.py main         # review diff against a ref

Environment:
    GEMINI_API_KEY        required
    GEMINI_REVIEW_MODEL   optional, default "gemini-2.5-pro"

Uses only the standard library so it runs before any project dependencies are installed.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_DIFF_CHARS = 200_000

PROMPT = """You are a senior engineer reviewing a change to a RAG code-assistant project.
The code was written by a different AI model. Be specific and skeptical.

Review the diff against the project's constitution and spec below. Report, most severe first:
1. Correctness bugs (with file and line from the diff).
2. Security issues — especially secret leakage and prompt injection.
3. Requirements the diff claims to implement but does not (cite FR-xxx IDs).
4. Missing tests for the behaviour changed.
Skip style nits. If the change is good, say so in one line.

<constitution>
{constitution}
</constitution>

<spec>
{spec}
</spec>

<diff>
{diff}
</diff>
"""


def git_diff(ref: str | None) -> str:
    args = ["git", "diff", "--cached"] if ref is None else ["git", "diff", ref]
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout


def read(path: str) -> str:
    p = ROOT / path
    return p.read_text(encoding="utf-8") if p.exists() else ""


def active_spec() -> str:
    feature = read(".specify/feature.json")
    folder = json.loads(feature).get("feature_directory", "") if feature else ""
    return read(f"{folder}/spec.md") if folder else ""


def review(diff: str, model: str, api_key: str) -> str:
    prompt = PROMPT.format(
        constitution=read(".specify/memory/constitution.md"),
        spec=active_spec(),
        diff=diff[:MAX_DIFF_CHARS],
    )
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode()
    request = urllib.request.Request(
        API_URL.format(model=model),
        data=body,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        data = json.load(response)
    return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set.", file=sys.stderr)
        return 2
    diff = git_diff(sys.argv[1] if len(sys.argv) > 1 else None)
    if not diff.strip():
        print("Nothing to review (no staged changes / empty diff).")
        return 0
    model = os.environ.get("GEMINI_REVIEW_MODEL", "gemini-2.5-pro")
    try:
        print(f"## Cross-review by {model}\n")
        print(review(diff, model, api_key))
    except urllib.error.HTTPError as err:
        print(f"Gemini API error {err.code}: {err.read().decode()[:500]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
