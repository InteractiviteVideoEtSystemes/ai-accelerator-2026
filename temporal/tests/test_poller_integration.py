"""Integration test for the worker intake poller (``_poll_once``).

The poller bridges Supabase (request rows) and Temporal (workflow start). Here
the Supabase REST client is monkeypatched and a fake Temporal client records
``start_workflow`` calls, so we assert the atomic-claim contract and the workflow
arguments without a running stack.
"""
from __future__ import annotations

from src import poller
from src.clients import supabase_rest
from src.config import settings
from src.workflows.ai.summarize_workflow import SummarizeDocumentInput


class _FakeClient:
    def __init__(self):
        self.started: list[dict] = []

    async def start_workflow(self, run, arg, *, id, task_queue):
        self.started.append({"run": run, "arg": arg, "id": id, "task_queue": task_queue})


def _row(request_id="r1"):
    return {
        "id": request_id,
        "storage_path": f"folder/{request_id}.txt",
        "mime_type": "text/plain",
        "original_filename": f"{request_id}.txt",
    }


async def test_poll_once_claims_then_starts_workflow(monkeypatch):
    monkeypatch.setattr(supabase_rest, "fetch_pending", lambda: [_row("r1")])
    monkeypatch.setattr(supabase_rest, "claim_request", lambda rid, wf: True)

    client = _FakeClient()
    await poller._poll_once(client)

    assert len(client.started) == 1
    started = client.started[0]
    assert started["id"] == "summarize-r1"
    assert started["task_queue"] == settings.temporal_task_queue
    arg = started["arg"]
    assert isinstance(arg, SummarizeDocumentInput)
    assert arg.request_id == "r1"
    assert arg.storage_path == "folder/r1.txt"
    assert arg.mime_type == "text/plain"


async def test_poll_once_skips_when_claim_lost(monkeypatch):
    # Another worker won the row: claim_request returns False -> no workflow start.
    monkeypatch.setattr(supabase_rest, "fetch_pending", lambda: [_row("r1")])
    monkeypatch.setattr(supabase_rest, "claim_request", lambda rid, wf: False)

    client = _FakeClient()
    await poller._poll_once(client)

    assert client.started == []


async def test_poll_once_processes_each_pending_row(monkeypatch):
    monkeypatch.setattr(supabase_rest, "fetch_pending", lambda: [_row("r1"), _row("r2")])
    monkeypatch.setattr(supabase_rest, "claim_request", lambda rid, wf: True)

    client = _FakeClient()
    await poller._poll_once(client)

    ids = sorted(s["id"] for s in client.started)
    assert ids == ["summarize-r1", "summarize-r2"]
