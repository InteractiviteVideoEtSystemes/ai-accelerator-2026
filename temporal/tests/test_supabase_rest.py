"""Unit tests for the synchronous Supabase REST/Storage client.

All HTTP is mocked: we assert the request URLs/filters, the service-role auth
headers, and the boolean contract of the atomic ``claim_request`` PATCH. No
network and no running Supabase are required.
"""
from __future__ import annotations

import httpx
import pytest

from src.clients import supabase_rest
from src.config import settings


class _FakeResponse:
    def __init__(self, *, json_data=None, content=b"", raise_exc=None):
        self._json = json_data
        self.content = content
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise is not None:
            raise self._raise
        return None

    def json(self):
        return self._json


class _RecordingClient:
    """httpx.Client double recording the last request per verb."""

    last: dict = {}

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url, headers=None):
        type(self).last = {"verb": "GET", "url": url, "headers": headers}
        return type(self).get_response

    def patch(self, url, headers=None, json=None):
        type(self).last = {"verb": "PATCH", "url": url, "headers": headers, "json": json}
        return type(self).patch_response


@pytest.fixture
def recording(monkeypatch):
    _RecordingClient.last = {}
    _RecordingClient.get_response = _FakeResponse(json_data=[])
    _RecordingClient.patch_response = _FakeResponse(json_data=[])
    monkeypatch.setattr(httpx, "Client", _RecordingClient)
    monkeypatch.setattr(settings, "supabase_url", "http://sb:54321")
    monkeypatch.setattr(settings, "supabase_service_role_key", "svc-key")
    monkeypatch.setattr(settings, "documents_bucket", "documents")
    return _RecordingClient


def test_headers_use_service_role_key(recording):
    supabase_rest.fetch_pending()
    headers = recording.last["headers"]
    assert headers["apikey"] == "svc-key"
    assert headers["Authorization"] == "Bearer svc-key"


def test_fetch_pending_filters_unclaimed_uploaded(recording):
    recording.get_response = _FakeResponse(json_data=[{"id": "a"}])
    rows = supabase_rest.fetch_pending(limit=5)
    assert rows == [{"id": "a"}]
    url = recording.last["url"]
    assert "status=eq.uploaded" in url
    assert "workflow_id=is.null" in url
    assert "limit=5" in url


def test_download_object_returns_bytes(recording):
    recording.get_response = _FakeResponse(content=b"PDFBYTES")
    data = supabase_rest.download_object("folder/file.pdf")
    assert data == b"PDFBYTES"
    assert "/storage/v1/object/documents/folder/file.pdf" in recording.last["url"]


def test_claim_request_true_when_row_returned(recording):
    recording.patch_response = _FakeResponse(json_data=[{"id": "req-1"}])
    assert supabase_rest.claim_request("req-1", "summarize-req-1") is True
    url = recording.last["url"]
    # Atomic claim: only an unclaimed, still-uploaded row matches.
    assert "workflow_id=is.null" in url
    assert "status=eq.uploaded" in url
    assert recording.last["json"] == {"workflow_id": "summarize-req-1"}


def test_claim_request_false_when_already_claimed(recording):
    recording.patch_response = _FakeResponse(json_data=[])
    assert supabase_rest.claim_request("req-1", "summarize-req-1") is False


def test_update_row_issues_patch_by_id(recording):
    supabase_rest.update_row("req-9", {"status": "completed"})
    assert recording.last["verb"] == "PATCH"
    assert "id=eq.req-9" in recording.last["url"]
    assert recording.last["json"] == {"status": "completed"}


def _http_error() -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "boom",
        request=httpx.Request("GET", "http://sb:54321"),
        response=httpx.Response(500),
    )


def test_download_object_propagates_http_error(recording):
    recording.get_response = _FakeResponse(raise_exc=_http_error())
    with pytest.raises(httpx.HTTPStatusError):
        supabase_rest.download_object("folder/file.pdf")


def test_fetch_pending_propagates_http_error(recording):
    recording.get_response = _FakeResponse(raise_exc=_http_error())
    with pytest.raises(httpx.HTTPStatusError):
        supabase_rest.fetch_pending()


def test_update_row_propagates_http_error(recording):
    recording.patch_response = _FakeResponse(raise_exc=_http_error())
    with pytest.raises(httpx.HTTPStatusError):
        supabase_rest.update_row("req-1", {"status": "failed"})


def test_claim_request_propagates_http_error(recording):
    # A failed claim PATCH must raise (so the poller logs/retries), not be read as
    # "claim lost" (which returning False would imply).
    recording.patch_response = _FakeResponse(raise_exc=_http_error())
    with pytest.raises(httpx.HTTPStatusError):
        supabase_rest.claim_request("req-1", "summarize-req-1")
