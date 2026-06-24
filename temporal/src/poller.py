"""Intake poller for AI document summarization.

The `summaries` Edge Function records upload requests in `document_summaries`
(status=uploaded). The Supabase/Deno runtime has no production-grade Temporal
client, so this poller -- running inside the Python worker that owns the Temporal
client -- claims each pending request and starts the SummarizeDocumentWorkflow.
"""
from __future__ import annotations

import asyncio
import logging

from temporalio.client import Client

from .config import settings
from .clients import supabase_rest
from .workflows.ai.summarize_workflow import (
    SummarizeDocumentInput,
    SummarizeDocumentWorkflow,
)

logger = logging.getLogger(__name__)


async def run_intake_poller(client: Client) -> None:
    """Continuously claim uploaded requests and start their workflows."""
    logger.info("intake poller started interval=%ss", settings.summary_poll_interval_seconds)
    while True:
        try:
            await _poll_once(client)
        except Exception as exc:  # keep the poller alive across transient errors
            logger.warning("intake poll error: %s", exc)
        await asyncio.sleep(settings.summary_poll_interval_seconds)


async def _poll_once(client: Client) -> None:
    pending = await asyncio.to_thread(supabase_rest.fetch_pending)
    for row in pending:
        request_id = row["id"]
        workflow_id = f"summarize-{request_id}"
        claimed = await asyncio.to_thread(
            supabase_rest.claim_request, request_id, workflow_id
        )
        if not claimed:
            continue
        await client.start_workflow(
            SummarizeDocumentWorkflow.run,
            SummarizeDocumentInput(
                request_id=request_id,
                storage_path=row["storage_path"],
                mime_type=row["mime_type"],
                original_filename=row.get("original_filename", ""),
            ),
            id=workflow_id,
            task_queue=settings.temporal_task_queue,
        )
        logger.info("started workflow id=%s request=%s", workflow_id, request_id)
