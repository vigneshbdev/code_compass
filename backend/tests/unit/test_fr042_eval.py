"""FR-042 / SC-002 / SC-003 / NFR-001: eval dataset rules and metric maths (task T147)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codecompass.eval.dataset import DatasetError, check_expected_files, load, parse
from codecompass.eval.metrics import (
    QuestionResult,
    context_precision,
    context_recall,
    passes,
    summarise,
)

DATASET = Path(__file__).resolve().parents[3] / "eval" / "datasets" / "fastapi-template-v1.yaml"
SHA = "a" * 40


def _yaml(questions: list[str], commit: str = SHA) -> str:
    return (
        f"name: t\nversion: 1\nrepo: https://example.test/r\ncommit: {commit}\nquestions:\n"
        + "\n".join(questions)
    )


def _q(i: int, category: str, files: str = "[a.py]") -> str:
    return (
        f"  - id: q{i}\n    category: {category}\n    question: Q{i}?\n    expected_files: {files}"
    )


VALID = [
    _q(1, "identifier"),
    _q(2, "identifier"),
    _q(3, "followup"),
    _q(4, "not_found", "[]"),
    _q(5, "offtopic", "[]"),
] + [_q(i, "locate") for i in range(6, 12)]


def test_fr042_shipped_dataset_follows_the_rules_once_verified() -> None:
    dataset = load(DATASET, allow_unverified=True)
    assert 10 <= len(dataset.questions) <= 15
    assert dataset.label == "fastapi-template-v1" and len(dataset.commit) == 40


def test_fr042_unverified_dataset_is_refused_without_the_flag() -> None:
    text = DATASET.read_text()
    if "# UNVERIFIED" in text:  # until the author completes T148
        with pytest.raises(DatasetError, match="T148"):
            load(DATASET)


def test_fr042_valid_dataset_parses() -> None:
    assert len(parse(_yaml(VALID)).questions) == 11


@pytest.mark.parametrize(
    ("questions", "commit", "message"),
    [
        (VALID[:5], SHA, "10-15"),
        (VALID + [_q(i, "locate") for i in range(20, 26)], SHA, "10-15"),
        ([q.replace("identifier", "locate") for q in VALID], SHA, "identifier"),
        ([q.replace("offtopic", "locate") for q in VALID], SHA, "offtopic"),
        (VALID, "abc123", "40-character"),
        ([*VALID[:-1], _q(1, "locate")], SHA, "unique"),
        ([*VALID[:-1], _q(99, "locate", "[]")], SHA, "expected_files"),
        ([*VALID[:-1], _q(99, "nonsense")], SHA, "Unknown"),
    ],
)
def test_fr042_dataset_rules(questions: list[str], commit: str, message: str) -> None:
    with pytest.raises(DatasetError, match=message):
        parse(_yaml(questions, commit))


def test_fr042_expected_files_must_exist_at_the_commit() -> None:
    dataset = parse(_yaml(VALID))
    check_expected_files(dataset, {"a.py"})
    with pytest.raises(DatasetError, match=r"a\.py"):
        check_expected_files(dataset, {"b.py"})


def r(
    category: str,
    status: str,
    retrieved: list[str],
    expected: list[str],
    cites: int = 0,
    ms: int | None = 1000,
    faith: float | None = None,
) -> QuestionResult:
    return QuestionResult(
        id=category,
        category=category,
        answerable=category not in {"not_found", "offtopic"},
        expected_files=expected,
        retrieved_files=retrieved,
        status=status,
        valid_citations=cites,
        first_token_ms=ms,
        faithfulness=faith,
    )


def test_fr042_metric_maths() -> None:
    results = [
        r("locate", "complete", ["a.py", "b.py"], ["a.py"], cites=2, ms=1000, faith=1.0),
        r("explain", "unverified", ["c.py"], ["d.py"], cites=0, ms=3000, faith=0.5),
        r("identifier", "complete", ["e.py"], ["e.py"], cites=1, ms=2000),
        r("not_found", "not_found", [], [], ms=10),  # excluded from latency (no LLM call)
        r("offtopic", "complete", ["x.py"], [], cites=1, ms=5),  # should have been declined
    ]
    s = summarise(results)
    assert s["retrieval_hit_rate"] == round(2 / 3, 3)  # SC-002: answerable only
    assert s["citation_validity"] == 0.75  # 3 of 4 claim-making answers cite (SC-003)
    assert s["not_found_accuracy"] == 1.0 and s["offtopic_accuracy"] == 0.0
    assert s["latency_first_token_p50_ms"] == 2000  # NFR-001: answerable only
    assert s["faithfulness"] == 0.75 and s["errors"] == 0


def test_fr042_context_precision_and_recall_are_file_level() -> None:
    result = r("explain", "complete", ["a.py", "a.py", "b.py"], ["a.py", "c.py"])
    assert context_precision(result) == 0.5 and context_recall(result) == 0.5


def test_fr042_fail_under_gate() -> None:
    assert passes({"retrieval_hit_rate": 0.85}, 0.8)
    assert not passes({"retrieval_hit_rate": 0.7}, 0.8)
    assert not passes({"retrieval_hit_rate": None}, 0.8)
    assert passes({"retrieval_hit_rate": 0.1}, None)
