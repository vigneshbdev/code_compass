"""FR-030: secrets are redacted before anything is stored (task T039)."""

from __future__ import annotations

from pathlib import Path

import pytest

from codecompass.guardrails.redaction import SecretDetector
from tests.fixtures import repos

detector = SecretDetector()


@pytest.fixture(scope="module")
def guardrail(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return repos.guardrail_repo(tmp_path_factory.mktemp("g"))


@pytest.mark.parametrize("secret", repos.SECRETS, ids=lambda s: s.kind)
def test_fr030_every_planted_secret_is_redacted(
    guardrail: Path, secret: repos.PlantedSecret
) -> None:
    original = (guardrail / secret.path).read_text()
    assert secret.value in original  # sanity: the fixture really contains it
    redacted, count = detector.redact(original)
    assert secret.value not in redacted
    assert "[REDACTED:" in redacted
    assert count >= 1


def test_fr030_line_structure_is_preserved(guardrail: Path) -> None:
    original = (guardrail / "config" / "aws.py").read_text()
    redacted, _ = detector.redact(original)
    assert len(redacted.splitlines()) == len(original.splitlines())
    for before, after in zip(original.splitlines(), redacted.splitlines(), strict=True):
        if "AWS_" not in before:
            assert before == after  # untouched lines stay identical


def test_fr030_clean_code_is_unchanged() -> None:
    code = (
        "def parse_config(path: str) -> dict[str, str]:\n"
        "    ACCESS = 'read'\n"
        "    return {'key': path, 'password_field': 'password'}\n"
        "token_count = len(tokens)\n"
    )
    assert detector.redact(code) == (code, 0)


def test_fr030_short_entropy_fragments_are_ignored() -> None:
    """detect-secrets' entropy plugins report fragments like 'ACCE'; those are not secrets."""
    line = 'ACCESS_MODE = "3c"\n'
    assert detector.redact(line) == (line, 0)


def test_fr030_find_reports_kind_and_span() -> None:
    value = repos.SECRETS[0].value  # AWS access key
    text = f'KEY = "{value}"\n'
    findings = detector.find(text)
    assert len(findings) == 1
    assert text[findings[0].start : findings[0].end] == value
    assert findings[0].kind == "aws_access_key"
