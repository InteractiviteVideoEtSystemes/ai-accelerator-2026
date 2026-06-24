from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

logger = logging.getLogger(__name__)


@dataclass
class SummarizeDocumentInput:
    request_id: str
    storage_path: str
    mime_type: str
    original_filename: str


@workflow.defn
class SummarizeDocumentWorkflow:
    """Orchestrates: extract -> redact -> summarize (Claude/Azure) -> persist.

    The external LLM call is isolated in its own activity with a bounded retry
    policy. Any unrecoverable error marks the request ``failed`` with a message.
    """

    @workflow.run
    async def run(self, data: SummarizeDocumentInput) -> dict:
        # Quick activities (DB writes / downloads): retry transient failures only.
        quick_retry = RetryPolicy(maximum_attempts=5, maximum_interval=timedelta(seconds=10))
        # LLM call: sized timeout + backoff for 429/5xx/timeouts.
        llm_retry = RetryPolicy(maximum_attempts=4, maximum_interval=timedelta(seconds=30))

        try:
            await workflow.execute_activity(
                "set_status",
                args=[data.request_id, "extracting"],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=quick_retry,
            )

            text = await workflow.execute_activity(
                "extract_text",
                args=[data.storage_path, data.mime_type, data.original_filename],
                start_to_close_timeout=timedelta(seconds=60),
                retry_policy=quick_retry,
            )

            redacted = await workflow.execute_activity(
                "redact_personal_names",
                args=[text],
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=quick_retry,
            )

            await workflow.execute_activity(
                "set_status",
                args=[data.request_id, "summarizing"],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=quick_retry,
            )

            summary = await workflow.execute_activity(
                "summarize_with_claude",
                args=[redacted],
                start_to_close_timeout=timedelta(seconds=120),
                retry_policy=llm_retry,
            )

            await workflow.execute_activity(
                "save_summary",
                args=[data.request_id, summary, len(text)],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=quick_retry,
            )

            return {"request_id": data.request_id, "status": "completed"}

        except ActivityError as exc:
            message = _describe(exc)
            workflow.logger.warning("summarization failed id=%s error=%s", data.request_id, message)
            await workflow.execute_activity(
                "mark_failed",
                args=[data.request_id, message],
                start_to_close_timeout=timedelta(seconds=15),
                retry_policy=RetryPolicy(maximum_attempts=5),
            )
            return {"request_id": data.request_id, "status": "failed", "error": message}


def _describe(exc: ActivityError) -> str:
    cause = exc.cause
    if isinstance(cause, ApplicationError) and cause.message:
        return cause.message
    return str(cause) if cause else "Summarization failed"
