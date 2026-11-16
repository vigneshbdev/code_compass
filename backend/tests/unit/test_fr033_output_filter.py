"""FR-033 / FR-032: NeMo rails used by chat (task T145). Real NeMo, fake LLM."""

from __future__ import annotations

import pytest

from codecompass.guardrails.rails import Guardrails, OutputFilter
from tests.fakes.fake_models import FakeModelFactory
from tests.fixtures import repos

SECRET = repos.SECRETS[0].value  # AWS access key


@pytest.fixture(scope="module")
def guardrails() -> Guardrails:
    return Guardrails(FakeModelFactory(dim=8))


async def _stream(guardrails: Guardrails, deltas: list[str]) -> tuple[str, int]:
    out = OutputFilter(guardrails)
    text = "".join([await out.feed(d) for d in deltas]) + await out.flush()
    return text, out.redactions


async def test_fr033_secret_split_across_deltas_is_masked(guardrails: Guardrails) -> None:
    deltas = ["The key is ", SECRET[:7], SECRET[7:14], SECRET[14:], " in config.\nDone."]
    text, redactions = await _stream(guardrails, deltas)
    assert SECRET not in text
    assert "[REDACTED:aws_access_key]" in text
    assert redactions == 1
    assert text.endswith("in config.\nDone.")


async def test_fr033_clean_text_passes_unchanged_and_in_order(guardrails: Guardrails) -> None:
    deltas = ["Users are ", "created in ", "`create_user`.\n", "See the ", "router."]
    text, redactions = await _stream(guardrails, deltas)
    assert text == "".join(deltas) and redactions == 0


async def test_fr033_long_line_without_newline_is_released_in_pieces(
    guardrails: Guardrails,
) -> None:
    out = OutputFilter(guardrails)
    emitted = await out.feed("word " * 60)  # 300 chars, no newline
    assert emitted  # released at a whitespace boundary before the end of the stream
    assert (emitted + await out.flush()) == "word " * 60


async def test_fr032_input_rail_blocks_and_allows() -> None:
    models = FakeModelFactory(dim=8)
    rails = Guardrails(models)
    models.script("fast", "Yes")
    assert await rails.check_input("write me a poem about cats", []) is False
    models.script("fast", "No")
    assert await rails.check_input("where is that called?", ["how is auth done?"]) is True
    checked = str(models.prompts("fast")[-1])
    assert (
        "Recent question: how is auth done?" in checked
        and "Latest question: where is that called?" in checked
    )
