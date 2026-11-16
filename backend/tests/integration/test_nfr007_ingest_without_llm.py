"""NFR-007: ingestion explains LLM problems instead of failing vaguely (tasks T054, T055)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import ClientFactory
from tests.fakes.fake_models import FakeModelFactory
from tests.fixtures import repos
from tests.integration.ingest_helpers import upload_zip, wait_for


async def test_nfr007_ingest_refused_when_llm_key_missing(
    make_client: ClientFactory, tmp_path: Path
) -> None:
    async with make_client(
        model_factory=FakeModelFactory(dim=64, check_result="missing")
    ) as client:
        zipped = await client.post(
            "/api/codebases/zip",
            files={
                "file": ("m.zip", repos.zip_dir(repos.mini_ts_repo(tmp_path)), "application/zip")
            },
        )
        github = await client.post("/api/codebases/github", json={"url": "https://github.com/o/r"})
        listed = (await client.get("/api/codebases")).json()["items"]
    for response in (zipped, github):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "llm_unavailable"
        assert "API key" in response.json()["error"]["message"]
    assert listed == []  # nothing half-created


async def test_nfr007_embedding_failure_has_clear_message(
    make_client: ClientFactory, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    async def broken(texts: list[str]) -> list[list[float]]:
        raise RuntimeError("429 quota exceeded")

    fake_models.embedder.aembed_documents = broken  # type: ignore[method-assign]
    async with make_client() as client:
        created = await upload_zip(client, repos.zip_dir(repos.mini_ts_repo(tmp_path)))
        body = await wait_for(client, created["id"])
    assert body["status"] == "failed"
    assert body["error_code"] == "llm_unavailable"
    assert "embedding provider" in body["error"].lower()
