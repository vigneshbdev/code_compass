"""Embedding rate pacing (NFR-004, FR-004).

Free-tier provider keys have a tokens-per-minute cap (see .env.example).
Without pacing, a normal repo fails ingestion on the first burst. The pacer keeps a sliding
one-minute window under `EMBED_TOKENS_PER_MINUTE` and, if the provider still answers 429,
halves its own pace (the chars/4 estimate undercounts some tokenizers), waits for the delay
the provider asks for and retries up to `EMBED_RATE_LIMIT_RETRIES` times.
"""

from __future__ import annotations

import asyncio
import re
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar("T")

WINDOW_SECONDS = 60.0
DEFAULT_RETRY_SECONDS = 60.0
MAX_RETRY_SECONDS = 120.0
MIN_TOKENS_PER_MINUTE = 1000
REQUESTS_PER_WINDOW = 4  # each request <= 1/4 of the minute budget
_DELAY = re.compile(r"retry(?:Delay\"?:\s*\"|\s+in\s+)(\d+(?:\.\d+)?)s", re.IGNORECASE)


class RateLimited(Exception):
    """The provider kept rate-limiting after every retry."""


def is_rate_limit(exc: BaseException) -> bool:
    return getattr(exc, "status_code", None) == 429 or "RateLimit" in type(exc).__name__


def retry_delay(exc: BaseException) -> float:
    """Delay the provider asked for, else one minute (capped)."""
    match = _DELAY.search(str(exc))
    seconds = float(match.group(1)) if match else DEFAULT_RETRY_SECONDS
    return min(seconds, MAX_RETRY_SECONDS)


def token_batches(costs: Sequence[int], max_items: int, max_tokens: int) -> list[list[int]]:
    """Group item indexes into batches bounded by count and (if > 0) by total tokens."""
    batches: list[list[int]] = []
    current: list[int] = []
    used = 0
    for i, cost in enumerate(costs):
        over_tokens = max_tokens > 0 and used + cost > max_tokens
        if current and (len(current) >= max_items or over_tokens):
            batches.append(current)
            current, used = [], 0
        current.append(i)
        used += cost
    if current:
        batches.append(current)
    return batches


class EmbedPacer:
    def __init__(
        self,
        tokens_per_minute: int,
        retries: int,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._limit = tokens_per_minute
        self._retries = retries
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[tuple[float, int]] = deque()

    async def _wait_for_budget(self, tokens: int) -> None:
        if self._limit <= 0:
            return
        while True:
            now = self._clock()
            while self._sent and now - self._sent[0][0] >= WINDOW_SECONDS:
                self._sent.popleft()
            used = sum(t for _, t in self._sent)
            if not self._sent or used + tokens <= self._limit:
                return
            await self._sleep(WINDOW_SECONDS - (now - self._sent[0][0]))

    async def run(self, tokens: int, call: Callable[[], Awaitable[T]]) -> T:
        attempt = 0
        while True:
            await self._wait_for_budget(tokens)
            self._sent.append((self._clock(), tokens))
            try:
                return await call()
            except Exception as exc:
                if not is_rate_limit(exc):
                    raise
                if attempt >= self._retries:
                    raise RateLimited(str(exc)) from exc
                attempt += 1
                if self._limit > 0:  # our token estimate undercounts: learn a lower pace
                    self._limit = max(MIN_TOKENS_PER_MINUTE, self._limit // 2)
                await self._sleep(retry_delay(exc))

    @property
    def tokens_per_minute(self) -> int:
        return self._limit
