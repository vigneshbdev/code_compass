"""SPA serving (task T026): client routes fall back to index.html, /api/* never does."""

from __future__ import annotations

from pathlib import Path

from codecompass.config import Settings
from tests.conftest import ClientFactory


def _static(tmp_path: Path) -> Path:
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>CodeCompass</title>")
    (static / "assets" / "app.js").write_text("console.log('ok')")
    (static / "favicon.svg").write_text("<svg/>")
    return static


async def test_spa_serves_index_assets_and_client_routes(
    make_client: ClientFactory, settings: Settings, tmp_path: Path
) -> None:
    with_static = settings.model_copy(update={"static_dir": _static(tmp_path)})
    async with make_client(settings=with_static) as client:
        assert "CodeCompass" in (await client.get("/")).text
        assert (await client.get("/assets/app.js")).status_code == 200
        assert (await client.get("/favicon.svg")).text == "<svg/>"
        deep = await client.get("/codebases/123/chat")  # client-side route
        assert deep.status_code == 200 and "CodeCompass" in deep.text


async def test_spa_does_not_swallow_unknown_api_paths(
    make_client: ClientFactory, settings: Settings, tmp_path: Path
) -> None:
    with_static = settings.model_copy(update={"static_dir": _static(tmp_path)})
    async with make_client(settings=with_static) as client:
        response = await client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Not found."}}


async def test_spa_blocks_path_traversal(
    make_client: ClientFactory, settings: Settings, tmp_path: Path
) -> None:
    (tmp_path / "secret.txt").write_text("top secret")
    with_static = settings.model_copy(update={"static_dir": _static(tmp_path)})
    async with make_client(settings=with_static) as client:
        response = await client.get("/..%2Fsecret.txt")
    assert "top secret" not in response.text
