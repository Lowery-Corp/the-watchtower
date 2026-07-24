import uuid
from dataclasses import dataclass
from typing import Any
from kombu.exceptions import OperationalError
from celery.result import AsyncResult

from offload_tasks.celery_app import celery_app
from schemas.webhook import Event


FILE_INGESTION_TASK = "tasks.event_load.remote_trigger"
DEFAULT_FILE_INGESTION_QUEUE = "event_logs"


class TaskQueueError(RuntimeError):
    pass


@dataclass(frozen=True)
class QueuedTask:
    celery_task_id: str
    task_name: str
    queue_name: str | None = None


def enqueue_task(
    task_name: str,
    *,
    kwargs: dict[str, Any] | None = None,
    queue_name: str | None = None,
    task_id: str | None = None,
) -> QueuedTask:
    try:
        result: AsyncResult = celery_app.send_task( # type: ignore
            task_name,
            kwargs=kwargs or {},
            queue=queue_name,
            task_id=task_id,
        )
        print(f"Enqueued task {task_name} with ID {result.id} to queue {queue_name}", flush=True) # type: ignore
    except OperationalError as exc:
        raise TaskQueueError("Could not publish task to Celery broker") from exc

    print(f"Task {task_name} enqueued with ID {result.id} to queue {queue_name}", flush=True) # type: ignore

    return QueuedTask(
        celery_task_id=result.id,
        task_name=task_name,
        queue_name=queue_name,
    )

async def enqueue_event_log_ingestion_task(
    *,
    event: Event,
    queue_name: str = DEFAULT_FILE_INGESTION_QUEUE,
) -> QueuedTask:

    return enqueue_task(
        task_name=FILE_INGESTION_TASK,
        kwargs=event.model_dump(),
        queue_name=queue_name,
    )
