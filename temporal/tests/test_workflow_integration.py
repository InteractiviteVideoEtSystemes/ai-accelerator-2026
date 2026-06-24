"""Integration test: the real SummarizeDocumentWorkflow driving the real
activities end-to-end inside a Temporal time-skipping test environment.

Only the two external boundaries are doubled: the Azure/Claude HTTP call (mocked
httpx) and Supabase (an in-memory store). This exercises the full
extract -> redact -> summarize -> persist wiring and the failure -> ``failed``
path, with no network and no running stack.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from src.activities import ai_summarization
from src.clients import supabase_rest
from src.config import settings
from src.workflows.ai.summarize_workflow import (
    SummarizeDocumentInput,
    SummarizeDocumentWorkflow,
)

ALL_ACTIVITIES = [
    ai_summarization.set_status,
    ai_summarization.extract_text,
    ai_summarization.redact_personal_names,
    ai_summarization.summarize_with_claude,
    ai_summarization.save_summary,
    ai_summarization.mark_failed,
]


class _FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"content": [{"type": "text", "text": "An English summary."}]}


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, *a, **k):
        return _FakeResponse()


@pytest.fixture
def fake_boundaries(monkeypatch):
    """In-memory Supabase + mocked Azure/Claude HTTP.

    Returns a recorder exposing: ``store`` (final row state per id), ``updates``
    (ordered list of (request_id, fields) for every write), and ``claude_inputs``
    (every user prompt sent to Claude) so tests can assert transition order and
    that redacted text -- not the raw name -- reaches the model.
    """
    store: dict[str, dict] = {}
    updates: list[tuple[str, dict]] = []
    claude_inputs: list[str] = []

    def fake_update_row(request_id, fields):
        updates.append((request_id, dict(fields)))
        store.setdefault(request_id, {}).update(fields)

    class _RecordingClient(_FakeClient):
        def post(self, url, headers=None, json=None):
            claude_inputs.append(json["messages"][0]["content"])
            return _FakeResponse()

    monkeypatch.setattr(supabase_rest, "update_row", fake_update_row)
    monkeypatch.setattr(
        supabase_rest,
        "download_object",
        lambda path: "Le rapport de Monsieur Jean Dupont est complet et détaillé.".encode("utf-8"),
    )
    monkeypatch.setattr(httpx, "Client", _RecordingClient)
    monkeypatch.setattr(settings, "azure_ai_inference_endpoint", "https://example.azure.com/")
    monkeypatch.setattr(settings, "azure_ai_api_key", "secret-key")
    monkeypatch.setattr(settings, "summarization_max_input_bytes", 524288)
    monkeypatch.setattr(settings, "summarization_chunk_threshold_bytes", 131072)

    class _Recorder:
        pass

    rec = _Recorder()
    rec.store = store
    rec.updates = updates
    rec.claude_inputs = claude_inputs
    return rec


async def _run(env: WorkflowEnvironment, data: SummarizeDocumentInput) -> dict:
    async with Worker(
        env.client,
        task_queue="ai-test",
        workflows=[SummarizeDocumentWorkflow],
        activities=ALL_ACTIVITIES,
        activity_executor=ThreadPoolExecutor(max_workers=4),
    ):
        return await env.client.execute_workflow(
            SummarizeDocumentWorkflow.run,
            data,
            id=f"wf-{data.request_id}",
            task_queue="ai-test",
        )


async def test_workflow_completes_and_persists_summary(fake_boundaries):
    async with await WorkflowEnvironment.start_time_skipping() as env:
        result = await _run(
            env,
            SummarizeDocumentInput(
                request_id="req-ok",
                storage_path="folder/doc.txt",
                mime_type="text/plain",
                original_filename="doc.txt",
            ),
        )

    assert result["status"] == "completed"
    row = fake_boundaries.store["req-ok"]
    assert row["status"] == "completed"
    assert row["summary"] == "An English summary."
    assert row["extracted_char_count"] > 0

    # The status must progress in the documented order, not jump straight to done.
    statuses = [fields["status"] for (_id, fields) in fake_boundaries.updates if "status" in fields]
    assert statuses == ["extracting", "summarizing", "completed"]

    # The redacted text -- never the raw personal name -- must reach Claude.
    assert fake_boundaries.claude_inputs, "Claude was never called"
    sent = fake_boundaries.claude_inputs[0]
    assert "Jean Dupont" not in sent
    assert "Monsieur" not in sent
    assert "[nom]" in sent


async def test_workflow_marks_failed_on_unsupported_mime(fake_boundaries):
    async with await WorkflowEnvironment.start_time_skipping() as env:
        result = await _run(
            env,
            SummarizeDocumentInput(
                request_id="req-bad",
                storage_path="folder/image.png",
                mime_type="image/png",
                original_filename="image.png",
            ),
        )

    assert result["status"] == "failed"
    row = fake_boundaries.store["req-bad"]
    assert row["status"] == "failed"
    assert row["error_message"]
    # Claude must not be called when extraction already failed.
    assert fake_boundaries.claude_inputs == []


async def test_workflow_marks_failed_when_provider_not_configured(fake_boundaries, monkeypatch):
    # Extraction/redaction succeed, but the summarize step has no Azure config:
    # the workflow must end in `failed` with the provider error, having advanced
    # through extracting -> summarizing first.
    monkeypatch.setattr(settings, "azure_ai_inference_endpoint", "")
    monkeypatch.setattr(settings, "azure_ai_api_key", "")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        result = await _run(
            env,
            SummarizeDocumentInput(
                request_id="req-noprov",
                storage_path="folder/doc.txt",
                mime_type="text/plain",
                original_filename="doc.txt",
            ),
        )

    assert result["status"] == "failed"
    row = fake_boundaries.store["req-noprov"]
    assert row["status"] == "failed"
    assert "not configured" in row["error_message"].lower()
    statuses = [fields["status"] for (_id, fields) in fake_boundaries.updates if "status" in fields]
    assert statuses == ["extracting", "summarizing", "failed"]
