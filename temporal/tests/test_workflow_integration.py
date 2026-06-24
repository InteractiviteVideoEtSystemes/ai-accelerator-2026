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
    """In-memory Supabase store + mocked Azure/Claude HTTP; returns the store."""
    store: dict[str, dict] = {}

    def fake_update_row(request_id, fields):
        store.setdefault(request_id, {}).update(fields)

    monkeypatch.setattr(supabase_rest, "update_row", fake_update_row)
    monkeypatch.setattr(
        supabase_rest,
        "download_object",
        lambda path: "Le rapport de Monsieur Jean Dupont est complet et détaillé.".encode("utf-8"),
    )
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    monkeypatch.setattr(settings, "azure_ai_inference_endpoint", "https://example.azure.com/")
    monkeypatch.setattr(settings, "azure_ai_api_key", "secret-key")
    monkeypatch.setattr(settings, "summarization_max_input_bytes", 524288)
    monkeypatch.setattr(settings, "summarization_chunk_threshold_bytes", 131072)
    return store


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
    row = fake_boundaries["req-ok"]
    assert row["status"] == "completed"
    assert row["summary"] == "An English summary."
    assert row["extracted_char_count"] > 0


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
    row = fake_boundaries["req-bad"]
    assert row["status"] == "failed"
    assert row["error_message"]
