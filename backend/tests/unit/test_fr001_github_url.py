"""FR-001: only public GitHub repo URLs are accepted (task T033)."""

from __future__ import annotations

import pytest

from codecompass.api.errors import AppError, ErrorCode
from codecompass.ingestion.sources import GithubRef, parse_github_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://github.com/fastapi/full-stack-fastapi-template",
            GithubRef("fastapi", "full-stack-fastapi-template", None),
        ),
        (
            "https://github.com/fastapi/full-stack-fastapi-template/",
            GithubRef("fastapi", "full-stack-fastapi-template", None),
        ),
        (
            "https://github.com/fastapi/full-stack-fastapi-template.git",
            GithubRef("fastapi", "full-stack-fastapi-template", None),
        ),
        ("https://github.com/a-b/c.d_e/tree/v1.2.3", GithubRef("a-b", "c.d_e", "v1.2.3")),
        ("https://github.com/o/r/tree/feature/x", GithubRef("o", "r", "feature/x")),
        ("  https://github.com/o/r  ", GithubRef("o", "r", None)),
    ],
)
def test_fr001_parses_valid_urls(url: str, expected: GithubRef) -> None:
    assert parse_github_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/o/r",  # not https
        "https://gitlab.com/o/r",  # other host
        "https://github.com/o",  # no repo
        "https://github.com/o/r/blob/main/x.py",  # file, not repo
        "https://github.com.evil.test/o/r",  # look-alike host
        "git@github.com:o/r.git",
        "",
    ],
)
def test_fr001_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(AppError) as info:
        parse_github_url(url)
    assert info.value.code is ErrorCode.INVALID_GITHUB_URL
