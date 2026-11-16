"""Server-sent events for chat (contracts/http-api.md "Chat", task T143)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class ChatEvent:
    name: str  # meta | token | citations | done | error
    data: dict[str, Any]

    def sse(self) -> str:
        return f"event: {self.name}\ndata: {json.dumps(self.data, default=str)}\n\n"
