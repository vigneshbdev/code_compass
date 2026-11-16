"""Evaluation metrics (FR-042, SC-002, SC-003, NFR-001; contracts/eval-dataset.md; T147)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuestionResult:
    id: str
    category: str
    answerable: bool
    expected_files: list[str]
    retrieved_files: list[str]  # files in the packed context, in order
    status: str  # complete | unverified | not_found | declined | error
    valid_citations: int
    first_token_ms: int | None
    answer: str = ""
    question: str = ""
    contexts: list[str] = field(default_factory=list)
    trace_id: str | None = None
    faithfulness: float | None = None


def _share(hits: int, total: int) -> float | None:
    return round(hits / total, 3) if total else None


def hit(result: QuestionResult) -> bool:
    return any(f in result.retrieved_files for f in result.expected_files)


def context_precision(result: QuestionResult) -> float:
    """Share of distinct retrieved files that are expected (file-level, no LLM)."""
    files = list(dict.fromkeys(result.retrieved_files))
    return sum(f in result.expected_files for f in files) / len(files) if files else 0.0


def context_recall(result: QuestionResult) -> float:
    """Share of expected files that were retrieved."""
    if not result.expected_files:
        return 0.0
    return sum(f in result.retrieved_files for f in result.expected_files) / len(
        result.expected_files
    )


def summarise(results: list[QuestionResult]) -> dict[str, Any]:
    answerable = [r for r in results if r.answerable]
    claiming = [r for r in results if r.status in {"complete", "unverified"}]
    not_found = [r for r in results if r.category == "not_found"]
    offtopic = [r for r in results if r.category == "offtopic"]
    latencies = [r.first_token_ms for r in answerable if r.first_token_ms is not None]
    faith = [r.faithfulness for r in results if r.faithfulness is not None]
    return {
        "questions": len(results),
        "retrieval_hit_rate": _share(sum(hit(r) for r in answerable), len(answerable)),
        "citation_validity": _share(sum(r.valid_citations > 0 for r in claiming), len(claiming)),
        "faithfulness": round(statistics.mean(faith), 3) if faith else None,
        "context_precision": round(statistics.mean(context_precision(r) for r in answerable), 3)
        if answerable
        else None,
        "context_recall": round(statistics.mean(context_recall(r) for r in answerable), 3)
        if answerable
        else None,
        "not_found_accuracy": _share(
            sum(r.status == "not_found" for r in not_found), len(not_found)
        ),
        "offtopic_accuracy": _share(sum(r.status == "declined" for r in offtopic), len(offtopic)),
        "latency_first_token_p50_ms": int(statistics.median(latencies)) if latencies else None,
        "errors": sum(r.status == "error" for r in results),
    }


def passes(summary: dict[str, Any], fail_under: float | None) -> bool:
    """`--fail-under X` turns the report into a gate on retrieval hit-rate (SC-002)."""
    if fail_under is None:
        return True
    rate = summary.get("retrieval_hit_rate")
    return rate is not None and rate >= fail_under
