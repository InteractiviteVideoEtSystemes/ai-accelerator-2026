"""Unit tests for ``summarize_with_claude`` with a fully mocked Azure/Claude HTTP
client -- no network, per the SPEC's offline-by-default rule. Covers the direct
path, the chunk + map-reduce path for large inputs, and the not-configured guard.
"""
from __future__ import annotations

import httpx
import pytest
from temporalio.exceptions import ApplicationError

from src.activities import ai_summarization
from src.config import settings


class _FakeResponse:
    def __init__(self, text: str):
        self._text = text

    def raise_for_status(self):
        return None

    def json(self):
        return {"content": [{"type": "text", "text": self._text}]}


class _FakeClient:
    """Context-manager httpx.Client double that records every POST."""

    posts: list[dict] = []
    reply_text = "An English summary."

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        type(self).posts.append({"url": url, "headers": headers, "json": json})
        return _FakeResponse(type(self).reply_text)


@pytest.fixture
def fake_azure(monkeypatch):
    _FakeClient.posts = []
    _FakeClient.reply_text = "An English summary."
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
    assert sent["json"]["model"] == "claude-sonnet-4-6"
    assert sent["headers"]["x-api-key"] == "secret-key"
    # The secret is sent only as the documented header, never in the URL.
    assert "secret-key" not in sent["url"]


def test_summarize_chunks_large_input_with_map_reduce(fake_azure, monkeypatch):
    # Tiny threshold forces chunking; several paragraphs -> multiple chunk calls
    # plus a final reduce call.
    monkeypatch.setattr(settings, "summarization_chunk_threshold_bytes", 40)
    text = "\n\n".join(f"Paragraphe numéro {i} avec du contenu." for i in range(6))
    result = ai_summarization.summarize_with_claude(text)
    assert result == "An English summary."
    # More than one call => map-reduce actually happened.
    assert len(fake_azure.posts) > 1
    # The reduce step uses the REDUCE system prompt.
    systems = [p["json"]["system"] for p in fake_azure.posts]
    assert any("partial summaries" in s for s in systems)


def test_summarize_requires_provider_config(monkeypatch):
    monkeypatch.setattr(settings, "azure_ai_inference_endpoint", "")
    monkeypatch.setattr(settings, "azure_ai_api_key", "")
    with pytest.raises(ApplicationError) as exc:
        ai_summarization.summarize_with_claude("texte")
    assert exc.value.type == "ProviderNotConfigured"
    assert exc.value.non_retryable is True
