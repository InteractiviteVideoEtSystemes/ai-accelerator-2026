"""Unit tests for the pure summarization helpers.

These cover redaction, plain-text extraction, and byte-budget chunking. They are
offline and have no Temporal or network dependencies.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from activities.summarization import (  # noqa: E402
    REDACTION_PLACEHOLDER,
    TXT_MIME,
    chunk_text,
    extract_text_from_bytes,
    redact_personal_names,
)


def test_redact_title_prefixed_name():
    text = "Le rapport de Monsieur Jean Dupont est complet."
    out = redact_personal_names(text)
    assert "Jean Dupont" not in out
    assert REDACTION_PLACEHOLDER in out


def test_redact_handles_abbreviated_titles():
    assert redact_personal_names("Contact: M. Pierre Martin") == f"Contact: {REDACTION_PLACEHOLDER}"
    assert redact_personal_names("Mme Claire Bernard a signé.") == f"{REDACTION_PLACEHOLDER} a signé."


def test_redact_leaves_plain_capitalised_words():
    text = "Paris est la capitale de la France."
    assert redact_personal_names(text) == text


def test_redact_empty():
    assert redact_personal_names("") == ""


def test_extract_text_from_txt():
    data = "Bonjour le monde".encode("utf-8")
    assert extract_text_from_bytes(data, TXT_MIME, "doc.txt") == "Bonjour le monde"


def test_extract_unsupported_mime_raises():
    try:
        extract_text_from_bytes(b"data", "image/png", "x.png")
    except ValueError:
        return
    raise AssertionError("expected ValueError for unsupported mime type")


def test_chunk_small_text_returns_single_chunk():
    assert chunk_text("short", 1024) == ["short"]


def test_chunk_empty_returns_empty_list():
    assert chunk_text("", 1024) == []


def test_chunk_respects_byte_budget():
    text = "\n\n".join(f"paragraph number {i} with some words" for i in range(50))
    max_bytes = 64
    chunks = chunk_text(text, max_bytes)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= max_bytes


def test_chunk_hard_splits_oversized_paragraph():
    text = "word " * 200  # single paragraph far larger than the budget
    max_bytes = 32
    chunks = chunk_text(text, max_bytes)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk.encode("utf-8")) <= max_bytes


def test_chunk_invalid_budget_raises():
    try:
        chunk_text("abc", 0)
    except ValueError:
        return
    raise AssertionError("expected ValueError for non-positive max_bytes")
