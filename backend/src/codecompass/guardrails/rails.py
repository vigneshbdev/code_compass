"""NeMo Guardrails around chat (FR-031…FR-033, research R9, task T145).

NeMo is the policy engine; CodeCompass's LCEL chain owns generation and streaming. We call
`LLMRails.check_async` for:
- the input rail (self check input) on the question plus recent questions; and
- the output rail (mask secrets action) on each streamed line, via `OutputFilter`.

Recorded decision (R9 spike, 2026-11-16): NeMo's own streaming output rails require NeMo to own
generation, which would bypass our LCEL chain and citation handling; `check_async` per line
keeps NeMo as the rail engine (≈13 ms per check) without that. History is put into the checked
text because NeMo's `history` prompt filter is empty in `check_async` mode (it fails closed).
"""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

from nemoguardrails import LLMRails, RailsConfig
from nemoguardrails.integrations.langchain.llm_adapter import LangChainLLMAdapter
from nemoguardrails.rails.llm.options import RailStatus, RailType

from codecompass.guardrails.redaction import SecretDetector
from codecompass.llm.factory import ModelFactory

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent / "config"
RECENT_QUESTIONS = 2
EMIT_AFTER_CHARS = 80  # without a newline, release at whitespace after this many chars
HARD_FLUSH_CHARS = 600  # flush even without whitespace (never seen in normal prose)


class Guardrails:
    def __init__(self, models: ModelFactory, detector: SecretDetector | None = None) -> None:
        self._detector = detector or SecretDetector()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            self._rails = LLMRails(
                RailsConfig.from_path(str(CONFIG_DIR)), llm=LangChainLLMAdapter(models.chat("fast"))
            )
        self._rails.register_action(self._mask_secrets, name="mask_secrets")

    async def _mask_secrets(self, text: str) -> str:
        return self._detector.redact(text)[0]

    async def check_input(self, question: str, recent_questions: list[str]) -> bool:
        """True when allowed. Fails closed: a rail error blocks (Constitution IV)."""
        recent = recent_questions[-RECENT_QUESTIONS:]
        checked = (
            "".join(f"Recent question: {q}\n" for q in recent) + f"Latest question: {question}"
        )
        try:
            result = await self._rails.check_async(
                [{"role": "user", "content": checked}], [RailType.INPUT]
            )
        except Exception:
            logger.exception("input rail failed; blocking")
            return False
        blocked: bool = result.status == RailStatus.BLOCKED
        return not blocked

    async def mask(self, text: str) -> str:
        """Output rail on one piece of streamed text (FR-033)."""
        if not text.strip():
            return text
        try:
            result = await self._rails.check_async(
                [{"role": "assistant", "content": text}], [RailType.OUTPUT]
            )
        except Exception:
            logger.exception("output rail failed; masking locally")
            return self._detector.redact(text)[0]
        return result.content if result.status == RailStatus.MODIFIED and result.content else text


class OutputFilter:
    """Line-buffered streaming filter: text reaches the client only after the output rail.

    Text is cut at a newline, or at whitespace once ~80 characters are buffered, so answers
    still stream word by word (FR-010). Provider-format secrets contain no whitespace, so one
    split across token deltas is always checked whole; keyword-style secrets
    (`password = "…"`) are already removed at ingestion (FR-030).
    """

    def __init__(self, guardrails: Guardrails) -> None:
        self._guardrails = guardrails
        self._buffer = ""
        self.redactions = 0

    async def _release(self, text: str) -> str:
        masked = await self._guardrails.mask(text)
        if masked != text:
            self.redactions += masked.count("[REDACTED:")
        return masked

    async def feed(self, delta: str) -> str:
        self._buffer += delta
        cut = self._buffer.rfind("\n") + 1
        if cut == 0 and len(self._buffer) > EMIT_AFTER_CHARS:
            cut = max(self._buffer.rfind(" "), self._buffer.rfind("\t")) + 1
            if cut == 0 and len(self._buffer) > HARD_FLUSH_CHARS:
                cut = len(self._buffer)
        if cut == 0:
            return ""
        ready, self._buffer = self._buffer[:cut], self._buffer[cut:]
        return await self._release(ready)

    async def flush(self) -> str:
        ready, self._buffer = self._buffer, ""
        return await self._release(ready) if ready else ""
