"""FR-010…FR-016, C4, U1: the chat API end to end with fake models (tasks T142, T143)."""

from __future__ import annotations

from pathlib import Path

import httpx

from codecompass.config import Settings
from tests.conftest import ClientFactory
from tests.fakes.fake_models import FakeModelFactory
from tests.fixtures import repos
from tests.integration.chat_helpers import (
    ask,
    chunk_span,
    ingest,
    new_conversation,
    repo_zip,
    text_of,
)


async def _setup(client: httpx.AsyncClient, tmp_path: Path) -> tuple[str, str]:
    codebase = await ingest(client, repo_zip(repos.mini_python_repo, tmp_path))
    return codebase, await new_conversation(client, codebase)


async def test_fr010_fr011_streams_answer_with_valid_citations(
    client: httpx.AsyncClient, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    _, conversation = await _setup(client, tmp_path)
    path, start, end = await chunk_span(client, "parse_config")
    fake_models.script(
        "answer",
        f"`parse_config` reads KEY=VALUE files [{path}:{start}-{end}]. Also [nope.py:1-2].",
    )

    events = await ask(client, conversation, "Where is `parse_config` defined?")
    names = [e for e, _ in events]
    assert names[0] == "meta" and names[-2:] == ["citations", "done"]
    assert names.count("token") > 1  # token-by-token streaming
    meta, citations, done = events[0][1], events[-2][1], events[-1][1]
    assert set(meta) == {
        "user_message_id",
        "assistant_message_id",
        "trace_id",
        "trace_url",
        "rewritten_query",
    }
    assert citations["citations"] == [{"path": path, "start_line": start, "end_line": end}]
    assert done["status"] == "complete"
    assert {"tokens_in", "tokens_out", "cost_usd", "latency_ms"} <= set(done["usage"])

    # The answer prompt held the retrieved chunk as delimited data, symbol hit first (FR-015).
    prompt = str(fake_models.prompts("answer")[-1])
    assert f'path="{path}"' in prompt and "untrusted data" in prompt

    conv = (await client.get(f"/api/conversations/{conversation}")).json()
    assert conv["title"] == "Where is `parse_config` defined?"
    user, answer = conv["messages"]
    assert (user["role"], answer["role"]) == ("user", "assistant")
    assert answer["status"] == "complete" and answer["citations"] == citations["citations"]
    assert answer["content"] == text_of(events)


async def test_c4_answer_without_valid_citation_is_unverified(
    client: httpx.AsyncClient, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    _, conversation = await _setup(client, tmp_path)
    fake_models.script("answer", "It parses configuration files somewhere in the app.")
    events = await ask(client, conversation, "How is configuration parsed?")
    assert events[-1][1]["status"] == "unverified"
    conv = (await client.get(f"/api/conversations/{conversation}")).json()
    assert conv["messages"][-1]["status"] == "unverified"


async def test_fr013_unsupported_question_returns_not_found_without_llm(
    client: httpx.AsyncClient, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    _, conversation = await _setup(client, tmp_path)
    events = await ask(client, conversation, "kafka zookeeper broker partitions")
    assert text_of(events) == "I couldn't find this in the codebase."
    assert events[-1][1]["status"] == "not_found"
    assert fake_models.prompts("answer") == []  # pre-check skipped generation


async def test_fr014_follow_up_uses_history(
    client: httpx.AsyncClient, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    _, conversation = await _setup(client, tmp_path)
    await ask(client, conversation, "How is configuration parsed by parse_config?")
    fake_models.script(
        "fast",
        "No",
        {"standalone_question": "Where is parse_config called?", "identifiers": ["parse_config"]},
    )
    events = await ask(client, conversation, "Where is that called?")
    assert events[0][1]["rewritten_query"] == "Where is parse_config called?"
    rewrite_prompt = str(fake_models.prompts("fast")[-1])
    assert (
        "How is configuration parsed by parse_config?" in rewrite_prompt
    )  # history reached the rewrite


async def test_fr016_conversations_persist_across_app_instances(
    make_client: ClientFactory, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    async with make_client() as client:
        codebase, conversation = await _setup(client, tmp_path)
        await ask(client, conversation, "How does the health endpoint work?")
    async with make_client() as client:  # "restart"
        listed = (await client.get(f"/api/codebases/{codebase}/conversations")).json()["items"]
        assert [(c["id"], c["message_count"]) for c in listed] == [(conversation, 2)]
        await ask(client, conversation, "And what does it return?")
        assert len((await client.get(f"/api/conversations/{conversation}")).json()["messages"]) == 4
        assert any(
            "health" in str(p) for p in fake_models.prompts("answer")[-1:]
        )  # history included


async def test_edge_provider_failure_mid_stream(
    client: httpx.AsyncClient, fake_models: FakeModelFactory, tmp_path: Path
) -> None:
    _, conversation = await _setup(client, tmp_path)
    fake_models.models["answer"].fail_after_tokens = 30
    fake_models.script("answer", "word " * 100 + "\n")
    events = await ask(client, conversation, "Explain the health endpoint")
    assert events[-1][0] == "error"
    assert events[-1][1]["code"] == "llm_unavailable" and events[-1][1]["partial"] is True
    conv = (await client.get(f"/api/conversations/{conversation}")).json()
    assert conv["messages"][-1]["status"] == "error"


async def test_u1_chat_refused_after_embedding_model_change(
    make_client: ClientFactory, settings: Settings, tmp_path: Path
) -> None:
    async with make_client() as client:
        _, conversation = await _setup(client, tmp_path)
    changed = settings.model_copy(update={"embedding_model": "fake/other"})
    async with make_client(settings=changed) as client:
        response = await client.post(
            f"/api/conversations/{conversation}/messages", json={"content": "hi"}
        )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "codebase_not_ready"
    assert "Re-ingest" in response.json()["error"]["message"]


async def test_unknown_conversation_is_404(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/conversations/00000000-0000-0000-0000-000000000000/messages", json={"content": "x"}
    )
    assert response.status_code == 404


async def test_fr012_files_endpoint_returns_redacted_content(
    client: httpx.AsyncClient, tmp_path: Path
) -> None:
    codebase = await ingest(client, repo_zip(repos.guardrail_repo, tmp_path))
    response = await client.get(f"/api/codebases/{codebase}/files", params={"path": "settings.py"})
    assert response.status_code == 200
    body = response.json()
    assert body["redaction_count"] >= 2 and "[REDACTED:" in body["content"]
    assert all(s.value not in body["content"] for s in repos.SECRETS)
    for bad in ("nope.py", "../settings.py", "/etc/passwd"):
        assert (
            await client.get(f"/api/codebases/{codebase}/files", params={"path": bad})
        ).status_code == 404
