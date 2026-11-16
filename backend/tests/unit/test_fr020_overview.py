"""FR-020 / FR-021: trimmed overview (task T149)."""

from __future__ import annotations

from pathlib import Path

from codecompass.ingestion.filters import select_files
from codecompass.overview.dependencies import dependencies
from codecompass.overview.languages import languages
from codecompass.overview.starters import starter_questions, template_questions
from tests.fakes.fake_models import FakeModelFactory
from tests.fakes.settings import make_settings
from tests.fixtures import repos


def _files(tmp_path: Path, builder) -> dict[str, str]:  # type: ignore[no-untyped-def]
    kept = select_files(builder(tmp_path), make_settings()).kept
    return {f.path: f.text for f in kept}


def test_fr020_language_breakdown(tmp_path: Path) -> None:
    langs = {row["language"]: row for row in languages(_files(tmp_path, repos.mini_python_repo))}
    assert langs["python"]["files"] == 6
    assert langs["python"]["lines"] > 200
    assert {"markdown", "toml"} <= set(langs)
    ordered = [r["files"] for r in languages(_files(tmp_path / "b", repos.mini_python_repo))]
    assert ordered == sorted(ordered, reverse=True)


def test_fr020_python_dependencies(tmp_path: Path) -> None:
    deps = dependencies(_files(tmp_path, repos.mini_python_repo))
    names = {(d["manifest"], d["name"], d["dev"]) for d in deps}
    assert ("pyproject.toml", "fastapi", False) in names
    assert ("pyproject.toml", "pytest", True) in names
    assert ("requirements.txt", "httpx", False) in names
    spec = next(d["spec"] for d in deps if d["name"] == "httpx")
    assert spec == "==0.27.0"
    assert all(d["ecosystem"] == "pypi" for d in deps)


def test_fr020_npm_dependencies(tmp_path: Path) -> None:
    deps = dependencies(_files(tmp_path, repos.mini_ts_repo))
    assert {(d["name"], d["dev"]) for d in deps} == {
        ("express", False),
        ("react", False),
        ("typescript", True),
    }
    assert all(d["ecosystem"] == "npm" for d in deps)


def test_fr020_poetry_and_broken_manifests_are_handled() -> None:
    files = {
        "pyproject.toml": '[tool.poetry.dependencies]\npython = "^3.12"\ndjango = "^5.0"\n',
        "package.json": "{ not json",
    }
    deps = dependencies(files)
    assert [(d["name"], d["spec"]) for d in deps] == [("django", "^5.0")]  # python itself skipped


async def test_fr021_llm_starters_are_used_when_valid() -> None:
    models = FakeModelFactory(dim=8)
    models.script(
        "fast",
        {
            "questions": [
                "How is auth done?",
                "Where are routes defined?",
                "How do tests run?",
                "What does crud.py do?",
            ]
        },
    )
    questions, source = await starter_questions(
        models.chat("fast"), {"languages": [], "dependencies": []}
    )
    assert source == "llm" and len(questions) == 4


async def test_fr021_invalid_llm_output_falls_back_to_templates() -> None:
    overview = {
        "languages": [{"language": "python", "files": 3, "lines": 90}],
        "dependencies": [
            {
                "name": "fastapi",
                "manifest": "pyproject.toml",
                "ecosystem": "pypi",
                "spec": "",
                "dev": False,
            }
        ],
    }
    for reply in (
        {"questions": ["only one?"]},
        {"questions": [f"q{i}" for i in range(7)]},
        "not json",
    ):
        models = FakeModelFactory(dim=8)
        models.script("fast", reply)
        questions, source = await starter_questions(models.chat("fast"), overview)
        assert source == "template" and 3 <= len(questions) <= 5
    assert any("fastapi" in q for q in template_questions(overview))
