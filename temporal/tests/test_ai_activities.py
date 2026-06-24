"""Unit tests for the AI summarization Temporal activities.

The activities are thin wrappers over ``supabase_rest`` and the pure
``summarization`` helpers. We monkeypatch ``supabase_rest`` (no network) and the
``settings`` singleton, then call the activity functions directly -- ``@activity.defn``
leaves the underlying function callable outside a workflow context.
"""
from __future__ import annotations

import pytest
from temporalio.exceptions import ApplicationError

from src.activities import ai_summarization
from src.clients import supabase_rest
from src.config import settings


@pytest.fixture
def captured_updates(monkeypatch):
    """Capture every ``supabase_rest.update_row`` call as (request_id, fields)."""
    calls: list[tuple[str, dict]] = []

    def _fake_update(request_id, fields):
        calls.append((request_id, dict(fields)))

    monkeypatch.setattr(supabase_rest, "update_row", _fake_update)
    return calls


def test_set_status_updates_row(captured_updates):
    assert ai_summarization.set_status("req-1", "extracting") is True
    assert captured_updates == [("req-1", {"status": "extracting"})]


def test_save_summary_persists_fields(captured_updates):
    assert ai_summarization.save_summary("req-2", "An English summary", 1234) is True
    request_id, fields = captured_updates[0]
    assert request_id == "req-2"
    assert fields["status"] == "completed"
    assert fields["summary"] == "An English summary"
    assert fields["extracted_char_count"] == 1234


def test_mark_failed_truncates_error(captured_updates):
    long_error = "x" * 5000
    assert ai_summarization.mark_failed("req-3", long_error) is True
    _, fields = captured_updates[0]
    assert fields["status"] == "failed"
    assert len(fields["error_message"]) == 1000


def test_extract_text_happy_path(monkeypatch):
    monkeypatch.setattr(supabase_rest, "download_object", lambda path: b"Bonjour le monde")
    monkeypatch.setattr(settings, "summarization_max_input_bytes", 524288)
    text = ai_summarization.extract_text("p/doc.txt", "text/plain", "doc.txt")
    assert text == "Bonjour le monde"


def test_extract_text_rejects_oversized_input(monkeypatch):
    monkeypatch.setattr(settings, "summarization_max_input_bytes", 10)
    monkeypatch.setattr(supabase_rest, "download_object", lambda path: b"this is far too long")
    with pytest.raises(ApplicationError) as exc:
        ai_summarization.extract_text("p/big.txt", "text/plain", "big.txt")
    assert exc.value.type == "InputTooLarge"
    assert exc.value.non_retryable is True


def test_extract_text_rejects_unsupported_mime(monkeypatch):
    monkeypatch.setattr(settings, "summarization_max_input_bytes", 524288)
    monkeypatch.setattr(supabase_rest, "download_object", lambda path: b"\x89PNG")
    with pytest.raises(ApplicationError) as exc:
        ai_summarization.extract_text("p/img.png", "image/png", "img.png")
    assert exc.value.type == "UnsupportedMimeType"
    assert exc.value.non_retryable is True


def test_extract_text_rejects_empty_extraction(monkeypatch):
    monkeypatch.setattr(settings, "summarization_max_input_bytes", 524288)
    monkeypatch.setattr(supabase_rest, "download_object", lambda path: b"   \n  ")
    with pytest.raises(ApplicationError) as exc:
        ai_summarization.extract_text("p/empty.txt", "text/plain", "empty.txt")
    assert exc.value.type == "EmptyExtraction"
    assert exc.value.non_retryable is True


def test_extract_text_rejects_oversized_extracted_text(monkeypatch):
    # Raw bytes are under the cap, but the decoded/extracted text expands beyond it
    # (e.g. a small compressed DOCX). The post-extraction guard must reject it.
    monkeypatch.setattr(settings, "summarization_max_input_bytes", 50)
    monkeypatch.setattr(supabase_rest, "download_object", lambda path: b"small zip bytes")
    monkeypatch.setattr(
        ai_summarization.summarization,
        "extract_text_from_bytes",
        lambda data, mime, name: "A" * 200,
    )
    with pytest.raises(ApplicationError) as exc:
        ai_summarization.extract_text("p/doc.docx", ai_summarization.summarization.DOCX_MIME, "doc.docx")
    assert exc.value.type == "InputTooLarge"
    assert exc.value.non_retryable is True


def test_redact_personal_names_activity(monkeypatch):
    out = ai_summarization.redact_personal_names("Le rapport de Monsieur Jean Dupont est complet.")
    # Assert the name is gone, the placeholder is present, and the rest is intact --
    # not merely that one substring is absent (which "" would also satisfy).
    assert "Jean Dupont" not in out
    assert "[nom]" in out
    assert out.startswith("Le rapport de ")
    assert out.endswith(" est complet.")
