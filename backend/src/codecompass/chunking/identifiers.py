"""Identifier splitting for the lexical index (FR-015, research R5/R6, task T047).

`getUserById` → `getUserById get user by id`, so a keyword search for "user by id" or the
exact identifier both match. Plain words pass through unchanged.
"""

from __future__ import annotations

import re

TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_.]*[A-Za-z0-9_]|[A-Za-z0-9_]+")
CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def _parts(token: str) -> list[str]:
    parts: list[str] = []
    for piece in re.split(r"[._]+", token):
        parts.extend(p.lower() for p in CAMEL.findall(piece))
    return parts


def split_identifiers(text: str) -> str:
    out: list[str] = []
    for token in TOKEN.findall(text):
        out.append(token)
        parts = _parts(token)
        if len(parts) > 1:
            out.extend(parts)
    return " ".join(out)
