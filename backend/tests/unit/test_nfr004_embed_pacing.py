"""NFR-004 / FR-004: ingestion paces embedding calls and survives provider rate limits."""

from __future__ import annotations

import pytest

from codecompass.ingestion.pacing import EmbedPacer, RateLimited, retry_delay, token_batches


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def time(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class RateLimitError(Exception):
    status_code = 429


def test_nfr004_batches_respect_count_and_token_budget() -> None:
    costs = [400, 400, 400, 900, 100]
    batches = token_batches(costs, max_items=2, max_tokens=1000)
    assert batches == [[0, 1], [2], [3, 4]]


def test_nfr004_oversized_item_gets_its_own_batch() -> None:
    assert token_batches([5000, 10], max_items=64, max_tokens=1000) == [[0], [1]]


def test_nfr004_retry_delay_is_read_from_the_provider_message() -> None:
    assert retry_delay(Exception("Please retry in 7.87s.")) == pytest.approx(7.87)
    assert retry_delay(Exception('"retryDelay": "59s"')) == 59
    assert retry_delay(Exception("no hint")) == 60


async def test_nfr004_pacer_waits_when_the_minute_budget_is_used() -> None:
    clock = FakeClock()
    pacer = EmbedPacer(tokens_per_minute=1000, retries=0, clock=clock.time, sleep=clock.sleep)

    async def call() -> str:
        return "ok"

    assert await pacer.run(600, call) == "ok"
    assert await pacer.run(600, call) == "ok"  # would exceed 1000 within the minute
    assert clock.slept and clock.now >= 60


async def test_nfr004_unlimited_pacer_never_waits() -> None:
    clock = FakeClock()
    pacer = EmbedPacer(tokens_per_minute=0, retries=0, clock=clock.time, sleep=clock.sleep)

    async def call() -> int:
        return 1

    for _ in range(5):
        await pacer.run(10_000, call)
    assert clock.slept == []


async def test_nfr004_rate_limit_is_waited_out_then_retried() -> None:
    clock = FakeClock()
    pacer = EmbedPacer(tokens_per_minute=0, retries=2, clock=clock.time, sleep=clock.sleep)
    attempts = 0

    async def call() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RateLimitError("Please retry in 5s.")
        return "ok"

    assert await pacer.run(10, call) == "ok"
    assert attempts == 3 and clock.slept == [5, 5]


async def test_nfr004_rate_limit_gives_up_after_the_retry_budget() -> None:
    clock = FakeClock()
    pacer = EmbedPacer(tokens_per_minute=0, retries=1, clock=clock.time, sleep=clock.sleep)

    async def call() -> str:
        raise RateLimitError("retry in 1s")

    with pytest.raises(RateLimited):
        await pacer.run(10, call)


async def test_nfr004_other_errors_are_not_retried() -> None:
    clock = FakeClock()
    pacer = EmbedPacer(tokens_per_minute=0, retries=3, clock=clock.time, sleep=clock.sleep)

    async def call() -> str:
        raise ValueError("bad key")

    with pytest.raises(ValueError):
        await pacer.run(10, call)
    assert clock.slept == []


async def test_nfr004_rate_limit_halves_the_pace() -> None:
    clock = FakeClock()
    pacer = EmbedPacer(tokens_per_minute=24_000, retries=3, clock=clock.time, sleep=clock.sleep)
    attempts = 0

    async def call() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RateLimitError("retry in 1s")
        return "ok"

    assert await pacer.run(100, call) == "ok"
    assert pacer.tokens_per_minute == 6_000
