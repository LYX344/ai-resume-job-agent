import asyncio
from typing import Any

from app.services.document_index_queue import RQDocumentIndexQueue
from app.workers.document_indexing import run_document_index_task_job


class FakeJob:
    id = "document-index-task-123"


class FakeRQQueue:
    def __init__(self) -> None:
        self.enqueue_calls: list[dict[str, Any]] = []

    def enqueue(self, func, **kwargs):
        self.enqueue_calls.append({"func": func, **kwargs})
        return FakeJob()


def test_rq_document_index_queue_enqueues_worker_job() -> None:
    fake_queue = FakeRQQueue()
    document_queue = RQDocumentIndexQueue(
        fake_queue,  # type: ignore[arg-type]
        job_timeout_seconds=300,
        result_ttl_seconds=3600,
        failure_ttl_seconds=86400,
    )

    job_id = asyncio.run(
        document_queue.enqueue_document_index_task(
            task_id="task-123",
            file_name="notes.md",
            raw_data=b"# Notes",
        )
    )

    assert job_id == "document-index-task-123"
    assert fake_queue.enqueue_calls == [
        {
            "func": run_document_index_task_job,
            "kwargs": {
                "task_id": "task-123",
                "file_name": "notes.md",
                "raw_data": b"# Notes",
            },
            "job_id": "document-index-task-123",
            "job_timeout": 300,
            "result_ttl": 3600,
            "failure_ttl": 86400,
        }
    ]
