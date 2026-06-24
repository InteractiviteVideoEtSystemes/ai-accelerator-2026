"""Temporal activities for the AI document summarization workflow.

Activities are synchronous (executed in the worker thread pool). Network/parse
errors propagate so Temporal can retry; bad-input errors are raised as
non-retryable ApplicationErrors. The Azure Claude client is imported lazily so the
module imports without the SDK installed (e.g. for offline unit tests).
"""
from __future__ import annotations

import logging

from temporalio import activity
from temporalio.exceptions import ApplicationError

from ..config import settings
from ..clients import supabase_rest
from . import summarization

logger = logging.getLogger(__name__)


@activity.defn
def set_status(request_id: str, status: str) -> bool:
    supabase_rest.update_row(request_id, {"status": status})
    logger.info("summary status updated id=%s status=%s", request_id, status)
    return True


@activity.defn
def extract_text(storage_path: str, mime_type: str, original_filename: str) -> str:
    """Download the uploaded document and extract its text (512 KB cap enforced)."""
    data = supabase_rest.download_object(storage_path)
    if len(data) > settings.summarization_max_input_bytes:
        raise ApplicationError(
            f"Document exceeds the {settings.summarization_max_input_bytes} byte limit",
            type="InputTooLarge",
            non_retryable=True,
        )
    try:
        text = summarization.extract_text_from_bytes(data, mime_type, original_filename)
    except ValueError as exc:
        raise ApplicationError(str(exc), type="UnsupportedMimeType", non_retryable=True)
    if not text.strip():
        raise ApplicationError(
            "No extractable text found (scanned/image documents are not supported)",
            type="EmptyExtraction",
            non_retryable=True,
        )
    logger.info("extracted text path=%s chars=%d", storage_path, len(text))
    return text


@activity.defn
def redact_personal_names(text: str) -> str:
    redacted = summarization.redact_personal_names(text)
    logger.info("redacted personal names chars_in=%d chars_out=%d", len(text), len(redacted))
    return redacted


@activity.defn
def summarize_with_claude(text: str) -> str:
    """Summarize French text into English using Claude Sonnet 4.6 hosted on Azure."""
    if not settings.azure_ai_inference_endpoint or not settings.azure_ai_api_key:
        raise ApplicationError(
            "Azure AI inference endpoint/key not configured",
            type="ProviderNotConfigured",
            non_retryable=True,
        )

    threshold = settings.summarization_chunk_threshold_bytes
    if len(text.encode("utf-8")) <= threshold:
        return _call_claude(summarization.SYSTEM_PROMPT, text)

    # Map-reduce for large inputs: summarize each chunk, then summarize the joined
    # partial summaries.
    chunks = summarization.chunk_text(text, threshold)
    logger.info("summarizing in %d chunks", len(chunks))
    partials = [_call_claude(summarization.SYSTEM_PROMPT, chunk) for chunk in chunks]
    combined = "\n\n".join(partials)
    if len(combined.encode("utf-8")) <= threshold:
        return _call_claude(summarization.REDUCE_SYSTEM_PROMPT, combined)
    # Rare: even the partials are large -- summarize them in a second pass.
    return summarize_with_claude(combined)


def _call_claude(system_prompt: str, user_text: str) -> str:
    """Call Claude via the Azure AI Foundry Anthropic Messages endpoint.

    Verified request shape (see .env.example):
      POST {endpoint}anthropic/v1/messages?api-version=<version>
      headers: x-api-key, anthropic-version: 2023-06-01
    """
    import httpx

    base = settings.azure_ai_inference_endpoint.rstrip("/")
    url = f"{base}/anthropic/v1/messages?api-version={settings.azure_anthropic_api_version}"
    headers = {
        "x-api-key": settings.azure_ai_api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": settings.azure_ai_summary_deployment,
        "max_tokens": 1024,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_text}],
    }
    with httpx.Client(timeout=110.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        body = resp.json()
    blocks = body.get("content", [])
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()


@activity.defn
def save_summary(request_id: str, summary: str, char_count: int) -> bool:
    supabase_rest.update_row(
        request_id,
        {"status": "completed", "summary": summary, "extracted_char_count": char_count},
    )
    logger.info("summary saved id=%s chars=%d", request_id, char_count)
    return True


@activity.defn
def mark_failed(request_id: str, error_message: str) -> bool:
    supabase_rest.update_row(
        request_id,
        {"status": "failed", "error_message": error_message[:1000]},
    )
    logger.info("summary failed id=%s error=%s", request_id, error_message[:200])
    return True
