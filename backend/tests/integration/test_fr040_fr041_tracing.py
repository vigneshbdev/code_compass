"""FR-040 / FR-041 / FR-043: Langfuse tracing and feedback (task T146)."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import ClientFactory
from tests.fakes.capture_tracer import CaptureTracer
from tests.fakes.fake_models import FakeModelFactory
from tests.fixtures import repos
from tests.integration.chat_helpers import ask, chunk_span, ingest, new_conversation, repo_zip


async def test_fr040_one_trace_per_request_with_required_fields(
    make_client: ClientFactory,
    fake_models: FakeModelFactory,
    capture_tracer: CaptureTracer,
    tmp_path: Path,
) -> None:
    async with make_client(langfuse=capture_tracer) as client:
        conversation = await new_conversation(
            client, await ingest(client, repo_zip(repos.mini_python_repo, tmp_path))
        )
        path, start, end = await chunk_span(client, "parse_config")
        fake_models.script("answer", f"See [{path}:{start}-{end}].")
        events = await ask(client, conversation, "Where is `parse_config` defined?")
        conv = (await client.get(f"/api/conversations/{conversation}")).json()

    trace = capture_tracer.traces[-1]
    assert trace.name == "chat" and trace.session_id == conversation
    meta = trace.updates[-1]["metadata"]
    assert {
        "query",
        "rewritten_query",
        "retrieval",
        "guardrails",
        "latency_ms",
        "model",
        "prompt_versions",
    } <= set(meta)
    row = meta["retrieval"][0]
    assert {
        "path",
        "vector_rank",
        "vector_score",
        "lexical_rank",
        "symbol_hit",
        "fused_score",
        "packed",
    } <= set(row)
    assert set(meta["guardrails"]) == {
        "input",
        "injection_flagged_chunks",
        "output_redactions",
        "not_found_precheck",
    }
    assert {"input_rails", "rewrite", "retrieve", "first_token", "generate", "total"} <= set(
        meta["latency_ms"]
    )
    assert set(meta["prompt_versions"]) == {"rewrite", "answer"}  # FR-043

    kinds = {e.kind for e in trace.handler.events}  # type: ignore[attr-defined]
    assert {"retriever_end", "chat_model_start"} <= kinds  # LangChain spans nest in the trace
    scores = {
        s["name"]: s["value"] for s in capture_tracer.scores if s["trace_id"] == trace.trace_id
    }
    assert scores == {"citations_valid": 1, "citations_invalid": 0}

    answer = conv["messages"][-1]
    assert answer["trace_id"] == trace.trace_id == events[0][1]["trace_id"]
    assert answer["trace_url"] == f"http://langfuse.test/trace/{trace.trace_id}"


async def test_fr041_feedback_is_saved_and_scored(
    make_client: ClientFactory, capture_tracer: CaptureTracer, tmp_path: Path
) -> None:
    async with make_client(langfuse=capture_tracer) as client:
        conversation = await new_conversation(
            client, await ingest(client, repo_zip(repos.mini_python_repo, tmp_path))
        )
        await ask(client, conversation, "How does the health endpoint work?")
        user, answer = (await client.get(f"/api/conversations/{conversation}")).json()["messages"]
        ok = await client.put(
            f"/api/messages/{answer['id']}/feedback", json={"value": 1, "comment": "great"}
        )
        cleared = await client.put(f"/api/messages/{answer['id']}/feedback", json={"value": None})
        on_user = await client.put(f"/api/messages/{user['id']}/feedback", json={"value": 1})
        saved = (await client.get(f"/api/conversations/{conversation}")).json()["messages"][-1]
    assert ok.status_code == 204 and cleared.status_code == 204
    assert on_user.status_code == 404
    assert saved["feedback"] is None
    feedback = [s for s in capture_tracer.scores if s["name"] == "user_feedback"]
    assert feedback == [
        {"trace_id": answer["trace_id"], "name": "user_feedback", "value": 1, "comment": "great"}
    ]


async def test_fr007_deleting_a_codebase_deletes_its_traces(
    make_client: ClientFactory, capture_tracer: CaptureTracer, tmp_path: Path
) -> None:
    async with make_client(langfuse=capture_tracer) as client:
        codebase = await ingest(client, repo_zip(repos.mini_python_repo, tmp_path))
        conversation = await new_conversation(client, codebase)
        await ask(client, conversation, "How does the health endpoint work?")
        trace_id = capture_tracer.traces[-1].trace_id
        assert (await client.delete(f"/api/codebases/{codebase}")).status_code == 204
    assert capture_tracer.deleted == [trace_id]
