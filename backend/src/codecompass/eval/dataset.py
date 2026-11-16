"""Versioned evaluation dataset (FR-042, contracts/eval-dataset.md, task T147)."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CATEGORIES = {"locate", "explain", "dependency", "identifier", "followup", "not_found", "offtopic"}
ANSWERABLE_EXCLUDED = {"not_found", "offtopic"}
MIN_QUESTIONS, MAX_QUESTIONS = 10, 15
REQUIRED = {"identifier": 2, "followup": 1, "not_found": 1, "offtopic": 1}
UNVERIFIED = "# UNVERIFIED"


class DatasetError(ValueError):
    pass


@dataclass(frozen=True)
class Question:
    id: str
    category: str
    question: str
    expected_files: tuple[str, ...]
    history: tuple[str, ...] = ()

    @property
    def answerable(self) -> bool:
        return self.category not in ANSWERABLE_EXCLUDED


@dataclass(frozen=True)
class Dataset:
    name: str
    version: int
    repo: str
    commit: str
    k: int
    questions: tuple[Question, ...] = field(default_factory=tuple)

    @property
    def label(self) -> str:
        return f"{self.name}-v{self.version}"


def parse(text: str, *, allow_unverified: bool = False) -> Dataset:
    if not allow_unverified and UNVERIFIED in text:
        raise DatasetError(
            "The dataset still has '# UNVERIFIED' expected files. The author must verify them "
            "against the pinned commit first (task T148)."
        )
    data = yaml.safe_load(text)
    commit = str(data.get("commit", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise DatasetError("`commit` must be a full 40-character SHA.")
    questions = tuple(
        Question(
            id=str(q["id"]),
            category=str(q["category"]),
            question=str(q["question"]),
            expected_files=tuple(q.get("expected_files") or ()),
            history=tuple(q.get("history") or ()),
        )
        for q in data.get("questions", [])
    )
    if not MIN_QUESTIONS <= len(questions) <= MAX_QUESTIONS:
        raise DatasetError(
            f"Need {MIN_QUESTIONS}-{MAX_QUESTIONS} questions, found {len(questions)}."
        )
    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        raise DatasetError("Question ids must be unique.")
    unknown = {q.category for q in questions} - CATEGORIES
    if unknown:
        raise DatasetError(f"Unknown categories: {sorted(unknown)}")
    counts = Counter(q.category for q in questions)
    for category, minimum in REQUIRED.items():
        if counts[category] < minimum:
            raise DatasetError(f"Need at least {minimum} '{category}' question(s).")
    for q in questions:
        if q.answerable and not q.expected_files:
            raise DatasetError(f"{q.id}: answerable questions need expected_files.")
    return Dataset(
        str(data["name"]),
        int(data["version"]),
        str(data["repo"]),
        commit,
        int(data.get("k", 8)),
        questions,
    )


def load(path: Path, *, allow_unverified: bool = False) -> Dataset:
    return parse(path.read_text(), allow_unverified=allow_unverified)


def check_expected_files(dataset: Dataset, indexed_paths: set[str]) -> None:
    """A typo in expected_files must fail the run, not silently lower the score."""
    missing = sorted({f for q in dataset.questions for f in q.expected_files} - indexed_paths)
    if missing:
        raise DatasetError(f"expected_files not in the indexed commit: {missing}")
