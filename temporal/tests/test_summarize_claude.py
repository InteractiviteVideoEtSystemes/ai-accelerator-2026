"""Unit tests for ``summarize_with_claude`` with a fully mocked Azure/Claude HTTP
client -- no network, per the SPEC's offline-by-default rule. Covers the direct
path, the chunk + map-reduce path for large inputs, and the not-configured guard.
"""
from __future__ import annotations

import httpx
import pytest
from temporalio.exceptions import ApplicationError

from src.activities import ai_summarization
from src.activities.summarization import REDUCE_SYSTEM_PROMPT, SYSTEM_PROMPT
from src.config import settings


class _FakeResponse:
    def __init__(self, text: str = "", *, raise_exc=None, body=None):
        self._text = text
        self._raise = raise_exc
        self._body = body

    def raise_for_status(self):
        if self._raise is not None:
            raise self._raise
        return None

    def json(self):
        if self._body is not None:
            return self._body
        return {"content": [{"type": "text", "text": self._text}]}


class _FakeClient:
    """Context-manager httpx.Client double that records every POST.

    Behaviour is configured via class attributes so tests can inject HTTP errors,
    override the response body, or make the reply depend on the request payload.
    """

    posts: list[dict] = []
    reply_text = "An English summary."
    reply_fn = None  # Optional[Callable[[dict], str]]
    raise_exc = None  # Optional[Exception] raised by raise_for_status()
    body_override = None  # Optional[dict] returned verbatim by .json()

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        record = {"url": url, "headers": headers, "json": json}
        type(self).posts.append(record)
        if type(self).raise_exc is not None:
            return _FakeResponse(raise_exc=type(self).raise_exc)
        if type(self).body_override is not None:
            return _FakeResponse(body=type(self).body_override)
        text = type(self).reply_fn(json) if type(self).reply_fn else type(self).reply_text
        record["reply"] = text
        return _FakeResponse(text)


@pytest.fixture
def fake_azure(monkeypatch):
    _FakeClient.posts = []
    _FakeClient.reply_text = "An English summary."
    _FakeClient.reply_fn = None
    _FakeClient.raise_exc = None
    _FakeClient.body_override = None
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    monkeypatch.setattr(settings, "azure_ai_inference_endpoint", "https://example.azure.com/")
    monkeypatch.setattr(settings, "azure_ai_api_key", "secret-key")
    monkeypatch.setattr(settings, "azure_ai_summary_deployment", "claude-sonnet-4-6")
    monkeypatch.setattr(settings, "azure_anthropic_api_version", "2025-04-01-preview")
    return _FakeClient


def test_summarize_direct_path(fake_azure, monkeypatch):
    monkeypatch.setattr(settings, "summarization_chunk_threshold_bytes", 131072)
    result = ai_summarization.summarize_with_claude("Texte français court.")
    assert result == "An English summary."
    # Exactly one Claude call for a small input.
    assert len(fake_azure.posts) == 1
    sent = fake_azure.posts[0]
    # Full request contract -- a regression in URL/version/headers/prompt must fail.
    assert sent["url"] == (
        "https://example.azure.com/anthropic/v1/messages?api-version=2025-04-01-preview"
    )
    assert sent["headers"]["anthropic-version"] == "2023-06-01"
    assert sent["headers"]["content-type"] == "application/json"
    assert sent["headers"]["x-api-key"] == "secret-key"
    assert sent["json"]["model"] == "claude-sonnet-4-6"
    assert sent["json"]["system"] == SYSTEM_PROMPT
    assert sent["json"]["messages"] == [
        {"role": "user", "content": "Texte français court."}
    ]
    # The secret is sent only as the documented header, never in the URL.
    assert "secret-key" not in sent["url"]


def test_summarize_propagates_http_error(fake_azure, monkeypatch):
    # A non-2xx Azure response must surface (so Temporal can retry/fail), not be
    # silently swallowed into an empty summary.
    monkeypatch.setattr(settings, "summarization_chunk_threshold_bytes", 131072)
    fake_azure.raise_exc = httpx.HTTPStatusError(
        "500 Server Error",
        request=httpx.Request("POST", "https://example.azure.com/"),
        response=httpx.Response(500),
    )
    with pytest.raises(httpx.HTTPStatusError):
        ai_summarization.summarize_with_claude("texte")


def test_summarize_returns_empty_when_no_text_blocks(fake_azure, monkeypatch):
    # Malformed/empty content array -> empty string, never a crash.
    monkeypatch.setattr(settings, "summarization_chunk_threshold_bytes", 131072)
    fake_azure.body_override = {"content": []}
    assert ai_summarization.summarize_with_claude("texte") == ""


def test_summarize_chunks_large_input_with_map_reduce(fake_azure, monkeypatch):
    # Tiny threshold forces chunking; assert real map-reduce fidelity rather than
    # only that "more than one call happened".
    threshold = 60
    monkeypatch.setattr(settings, "summarization_chunk_threshold_bytes", threshold)
    fake_azure.reply_fn = lambda payload: "PARTIAL"
    text = "\n\n".join(
        f"Paragraphe numero {i} avec un peu de contenu ici." for i in range(3)
    )
    result = ai_summarization.summarize_with_claude(text)
    assert result == "An English summary." or result == "PARTIAL"

    map_posts = [p for p in fake_azure.posts if p["json"]["system"] == SYSTEM_PROMPT]
    reduce_posts = [
        p for p in fake_azure.posts if p["json"]["system"] == REDUCE_SYSTEM_PROMPT
    ]
    # One map call per chunk, and each chunk respected the byte budget.
    assert len(map_posts) > 1
    for p in map_posts:
        content = p["json"]["messages"][0]["content"]
        assert len(content.encode("utf-8")) <= threshold
    # Exactly one reduce call, fed precisely the joined partial summaries.
    assert len(reduce_posts) == 1
    combined_expected = "\n\n".join(p["reply"] for p in map_posts)
    assert reduce_posts[0]["json"]["messages"][0]["content"] == combined_expected
    # The reduce call is the final one.
    assert fake_azure.posts[-1] is reduce_posts[0]


def test_summarize_requires_provider_config(monkeypatch):
    monkeypatch.setattr(settings, "azure_ai_inference_endpoint", "")
    monkeypatch.setattr(settings, "azure_ai_api_key", "")
    with pytest.raises(ApplicationError) as exc:
        ai_summarization.summarize_with_claude("texte")
    assert exc.value.type == "ProviderNotConfigured"
    assert exc.value.non_retryable is True
