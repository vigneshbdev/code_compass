"""Secret detection and redaction (FR-030 at ingestion, FR-033 on output; research R9; T051).

Uses Yelp detect-secrets plugins (AWS, GitHub, Slack, Stripe, JWT, basic auth, private key,
keyword and high-entropy detectors) plus a few custom patterns. Each match is replaced *within
its line* by `[REDACTED:<kind>]`, so line numbers and citations stay correct.

detect-secrets returns secret values without positions, and its entropy plugins report short
fragments such as 'ACCE'. We locate each value in the line ourselves and ignore values shorter
than MIN_SECRET_LENGTH.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from detect_secrets.core.scan import scan_line
from detect_secrets.settings import default_settings

MIN_SECRET_LENGTH = 8
PLACEHOLDER = "[REDACTED:{kind}]"

# Provider key formats detect-secrets does not cover.
CUSTOM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("gemini_key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),  # literal-ok: key format to redact
    ("openai_key", re.compile(r"sk-(?:proj-)?[A-Za-z0-9_\-]{20,}")),
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")),
    ("langfuse_secret_key", re.compile(r"sk-lf-[0-9a-f\-]{20,}")),
)
PEM_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
PEM_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")
# Values detect-secrets' keyword plugin flags that are clearly not secrets.
NOT_SECRETS = re.compile(r"^(?:password|secret|token|changeme|example|none|null|true|false)$", re.I)


ENTROPY_KINDS = {"base64_high_entropy_string", "hex_high_entropy_string"}
MIN_ENTROPY_SECRET_LENGTH = 16


def _looks_like_key(value: str) -> bool:
    """Entropy-only findings count only when long and mixing letters with digits."""
    return (
        len(value) >= MIN_ENTROPY_SECRET_LENGTH
        and any(c.isdigit() for c in value)
        and any(c.isalpha() for c in value)
    )


@dataclass(frozen=True)
class Finding:
    start: int
    end: int
    kind: str


def _kind(detect_secrets_type: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", detect_secrets_type.lower()).strip("_")


def _merge(findings: list[Finding]) -> list[Finding]:
    merged: list[Finding] = []
    for f in sorted(findings, key=lambda f: (f.start, -(f.end - f.start))):
        if merged and f.start < merged[-1].end:
            last = merged[-1]
            if f.end > last.end:
                merged[-1] = Finding(last.start, f.end, last.kind)
            continue
        merged.append(f)
    return merged


class SecretDetector:
    def _line_findings(self, line: str, offset: int) -> list[Finding]:
        found: list[Finding] = []
        for secret in scan_line(line):
            value = secret.secret_value or ""
            if len(value) < MIN_SECRET_LENGTH or NOT_SECRETS.match(value):
                continue
            if _kind(secret.type) in ENTROPY_KINDS and not _looks_like_key(value):
                continue  # entropy plugins flag plain identifiers such as `token_count`
            for match in re.finditer(re.escape(value), line):
                found.append(
                    Finding(offset + match.start(), offset + match.end(), _kind(secret.type))
                )
        for kind, pattern in CUSTOM_PATTERNS:
            for match in pattern.finditer(line):
                found.append(Finding(offset + match.start(), offset + match.end(), kind))
        return found

    def find(self, text: str) -> list[Finding]:
        """All secret spans in `text` (character offsets), merged and sorted."""
        findings: list[Finding] = []
        offset = 0
        in_pem = False
        with default_settings():
            for line in text.splitlines(keepends=True):
                content = line.rstrip("\r\n")
                if in_pem or PEM_BEGIN.search(content):
                    in_pem = not PEM_END.search(content)
                    if content.strip():
                        findings.append(Finding(offset, offset + len(content), "private_key"))
                elif content.strip():
                    findings.extend(self._line_findings(content, offset))
                offset += len(line)
        # Detectors may label the same value differently; prefer the specific provider kind.
        specific = [f for f in findings if f.kind not in ENTROPY_KINDS | {"secret_keyword"}]
        generic = [f for f in findings if f not in specific]
        return _merge(specific + generic)

    def redact(self, text: str) -> tuple[str, int]:
        """(text with every secret replaced in place, number of secrets replaced)."""
        findings = self.find(text)
        if not findings:
            return text, 0
        out: list[str] = []
        cursor = 0
        for f in findings:
            out.append(text[cursor : f.start])
            out.append(PLACEHOLDER.format(kind=f.kind))
            cursor = f.end
        out.append(text[cursor:])
        return "".join(out), len(findings)
