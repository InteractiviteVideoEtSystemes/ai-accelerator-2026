from __future__ import annotations
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from temporalio.client import Client
from temporalio.worker import Worker

from .config import settings
from .activities import supabase_core, notifications, ai_summarization
from .poller import run_intake_poller
from .workflows.example.approval_workflow import ApprovalWorkflow
from .workflows.ai.summarize_workflow import SummarizeDocumentWorkflow

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Connecting to Temporal", extra={"address": settings.temporal_address, "namespace": settings.temporal_namespace})
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)

    activity_executor = ThreadPoolExecutor(max_workers=20)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[ApprovalWorkflow, SummarizeDocumentWorkflow],
        activities=[
            supabase_core.create_entity,
            supabase_core.update_entity_scd2,
            supabase_core.get_entity,
            supabase_core.append_event,
            supabase_core.create_relationship,
            notifications.send_email,
            notifications.send_notification,
            ai_summarization.set_status,
            ai_summarization.extract_text,
            ai_summarization.redact_personal_names,
            ai_summarization.summarize_with_claude,
            ai_summarization.save_summary,
            ai_summarization.mark_failed,
        ],
        activity_executor=activity_executor,
    )

    logger.info("Worker started", extra={"task_queue": settings.temporal_task_queue})

    tasks = [asyncio.create_task(worker.run())]
    if settings.ai_summarization_enabled:
        tasks.append(asyncio.create_task(run_intake_poller(client)))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
