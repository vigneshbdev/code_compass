#!/usr/bin/env python3
"""Create .env from .env.example with generated dev secrets (research R20, task T005).

Placeholders in .env.example:
  __GENERATE__            replaced by a fresh random value (64 hex chars) per variable
  __SAME_AS:<VAR>__       replaced by the value generated for <VAR>, so related settings match

Never overwrites an existing .env. Standard library only.
"""

from __future__ import annotations

import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / ".env.example"
TARGET = ROOT / ".env"
SAME_AS = re.compile(r"__SAME_AS:([A-Z0-9_]+)__")


def render(example: str) -> str:
    generated: dict[str, str] = {}
    lines = example.splitlines()
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#") and "__GENERATE__" in value:
            generated[key.strip()] = secrets.token_hex(32)

    out: list[str] = []
    for line in lines:
        key, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            name = key.strip()
            if name in generated:
                value = value.replace("__GENERATE__", generated[name])

            def same_as(match: re.Match[str]) -> str:
                ref = match.group(1)
                if ref not in generated:
                    sys.exit(f"{name}: __SAME_AS:{ref}__ refers to a variable that is not generated")
                return generated[ref]

            value = SAME_AS.sub(same_as, value)
            line = f"{key}{sep}{value}"
        out.append(line)
    return "\n".join(out) + "\n"


def main() -> int:
    if TARGET.exists():
        print(".env already exists, leaving it untouched.")
        return 0
    TARGET.write_text(render(EXAMPLE.read_text()))
    TARGET.chmod(0o600)
    print("Created .env with generated dev secrets. Now set GEMINI_API_KEY in .env.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
