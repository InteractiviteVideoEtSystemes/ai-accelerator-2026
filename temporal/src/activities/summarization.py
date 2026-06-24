"""Pure, dependency-light helpers for AI document summarization.

These functions contain no Temporal or network code so they can be unit-tested
offline. Heavy parsers (pypdf / python-docx) are imported lazily inside
``extract_text_from_bytes`` so the rest of the module imports cheaply.
"""
from __future__ import annotations

import io
import re

PDF_MIME = "application/pdf"
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TXT_MIME = "text/plain"

# French civility titles that commonly precede a person's name. Used for a
# deterministic, best-effort name redaction pass (defense-in-depth alongside the
# model prompt instruction to omit personal names).
_TITLE = r"(?:M\.|MM\.|Mr\.?|Mme\.?|Mlle\.?|Dr\.?|Me\.?|Pr\.?|Monsieur|Madame|Mademoiselle|Docteur|Professeur|Maitre|Maître)"
# One to three capitalised tokens following a title (accented letters included).
_NAME = r"[A-ZÀ-Þ][\wÀ-ÿ'’-]+(?:[ -][A-ZÀ-Þ][\wÀ-ÿ'’-]+){0,2}"
_NAME_AFTER_TITLE = re.compile(rf"\b{_TITLE}\s+{_NAME}")

REDACTION_PLACEHOLDER = "[nom]"


def redact_personal_names(text: str) -> str:
    """Remove person names that are explicitly introduced by a civility title.

    This is a conservative, deterministic pass (e.g. ``Monsieur Jean Dupont`` ->
    ``[nom]``). It intentionally only touches title-prefixed names to avoid
    stripping ordinary capitalised words; the model prompt provides the broader
    safeguard for names without a title.
    """
    if not text:
        return text
    return _NAME_AFTER_TITLE.sub(REDACTION_PLACEHOLDER, text)


def extract_text_from_bytes(data: bytes, mime_type: str, filename: str = "") -> str:
    """Extract UTF-8 text from PDF, DOCX, or plain-text bytes."""
    if mime_type == TXT_MIME or filename.lower().endswith(".txt"):
        return data.decode("utf-8", errors="replace")

    if mime_type == PDF_MIME or filename.lower().endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        parts = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(parts).strip()

    if mime_type == DOCX_MIME or filename.lower().endswith(".docx"):
        from docx import Document

        document = Document(io.BytesIO(data))
        return "\n".join(p.text for p in document.paragraphs).strip()

    raise ValueError(f"Unsupported mime_type for extraction: {mime_type}")


def chunk_text(text: str, max_bytes: int) -> list[str]:
    """Split ``text`` into chunks no larger than ``max_bytes`` (UTF-8), breaking
    on paragraph then line then hard boundaries to keep chunks coherent."""
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if len(text.encode("utf-8")) <= max_bytes:
        return [text] if text else []

    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        if current:
            chunks.append(current)
            current = ""

    for paragraph in text.split("\n\n"):
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
            continue
        flush()
        if len(paragraph.encode("utf-8")) <= max_bytes:
            current = paragraph
        else:
            # Paragraph alone is too big: hard-split on byte budget.
            for piece in _hard_split(paragraph, max_bytes):
                chunks.append(piece)
    flush()
    return chunks


def _hard_split(text: str, max_bytes: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = word if not current else f"{current} {word}"
        if len(candidate.encode("utf-8")) <= max_bytes:
            current = candidate
        else:
            if current:
                pieces.append(current)
            current = word
    if current:
        pieces.append(current)
    return pieces


SYSTEM_PROMPT = (
    "You are a translator-summarizer. The user provides French text. Produce a "
    "concise, faithful summary in English. Do not include any personal names "
    "(first names or surnames); refer to people generically (e.g. 'a manager'). "
    "Output English prose only, no preamble."
)

REDUCE_SYSTEM_PROMPT = (
    "You are a summarizer. The user provides several English partial summaries of "
    "one document. Combine them into a single concise, coherent English summary. "
    "Do not include any personal names. Output English prose only, no preamble."
)
