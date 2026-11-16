"""Eval reports: JSON + Markdown files and a stdout summary (FR-042, task T147)."""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codecompass.eval.metrics import QuestionResult, hit

TARGETS = {
    "retrieval_hit_rate": ">= 0.80 (SC-002)",
    "citation_validity": "1.00 (SC-003)",
    "latency_first_token_p50_ms": "<= 3000 (NFR-001)",
}


def _hit_cell(result: QuestionResult) -> str:
    if not result.answerable:
        return "-"
    return "yes" if hit(result) else "no"


def markdown(
    label: str, commit: str, summary: dict[str, Any], results: list[QuestionResult]
) -> str:
    lines = [
        f"# Eval report: {label}",
        "",
        f"Commit `{commit}`",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
    ]
    lines += [f"| {k} | {v} | {TARGETS.get(k, '')} |" for k, v in summary.items()]
    lines += [
        "",
        "| Question | Category | Status | Hit | Valid citations | First token ms | Trace |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r.id} | {r.category} | {r.status} | {_hit_cell(r)} | {r.valid_citations} "
            f"| {r.first_token_ms or '-'} | {r.trace_id or '-'} |"
        )
    return "\n".join(lines) + "\n"


def write(
    reports_dir: Path,
    label: str,
    commit: str,
    summary: dict[str, Any],
    results: list[QuestionResult],
) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    base = reports_dir / f"{label}-{stamp}"
    payload = {
        "dataset": label,
        "commit": commit,
        "summary": summary,
        "questions": [asdict(r) | {"hit": hit(r)} for r in results],
    }
    base.with_suffix(".json").write_text(json.dumps(payload, indent=2))
    base.with_suffix(".md").write_text(markdown(label, commit, summary, results))
    return base.with_suffix(".md")
