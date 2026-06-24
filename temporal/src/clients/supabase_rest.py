"""Minimal synchronous Supabase REST/Storage client for the worker.

Uses the service-role key (server-side only) to download uploaded documents from
Storage and to read/update ``document_summaries`` rows via PostgREST. Kept
dependency-light (httpx only) and synchronous so it can run inside the worker's
activity thread pool; the async intake poller calls it via ``asyncio.to_thread``.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_TABLE = "document_summaries"


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    if extra:
        headers.update(extra)
    return headers


def download_object(storage_path: str) -> bytes:
    """Download an object's bytes from the documents bucket."""
    url = f"{settings.supabase_url}/storage/v1/object/{settings.documents_bucket}/{storage_path}"
    with httpx.Client(timeout=30.0) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.content


def update_row(request_id: str, fields: dict[str, Any]) -> None:
    """PATCH a ``document_summaries`` row by id."""
    url = f"{settings.supabase_url}/rest/v1/{_TABLE}?id=eq.{request_id}"
    with httpx.Client(timeout=15.0) as client:
        resp = client.patch(
            url,
            headers=_headers({"Content-Type": "application/json", "Prefer": "return=minimal"}),
            json=fields,
        )
        resp.raise_for_status()


def fetch_pending(limit: int = 10) -> list[dict[str, Any]]:
    """Return uploaded requests that have not yet been assigned a workflow."""
    url = (
        f"{settings.supabase_url}/rest/v1/{_TABLE}"
        "?status=eq.uploaded&workflow_id=is.null"
        "&select=id,storage_path,mime_type,original_filename"
        f"&order=created_at.asc&limit={limit}"
    )
    with httpx.Client(timeout=15.0) as client:
        resp = client.get(url, headers=_headers())
        resp.raise_for_status()
        return resp.json()


def claim_request(request_id: str, workflow_id: str) -> bool:
    """Atomically claim a request by setting its workflow_id only if still unset.

    Returns True if this caller won the claim (so it should start the workflow).
    """
    url = (
        f"{settings.supabase_url}/rest/v1/{_TABLE}"
        f"?id=eq.{request_id}&workflow_id=is.null&status=eq.uploaded"
    )
    with httpx.Client(timeout=15.0) as client:
        resp = client.patch(
            url,
            headers=_headers(
                {"Content-Type": "application/json", "Prefer": "return=representation"}
            ),
            json={"workflow_id": workflow_id},
        )
        resp.raise_for_status()
        return len(resp.json()) > 0
