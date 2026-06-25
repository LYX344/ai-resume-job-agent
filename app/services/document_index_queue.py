from __future__ import annotations

import asyncio
from typing import Protocol

from redis import Redis
from rq import Queue

from app.core.config import settings
from app.workers.document_indexing import run_document_index_task_job


class DocumentIndexQueue(Protocol):
    async def enqueue_document_index_task(
        self,
        *,
        task_id: str,
        file_name: str,
        raw_data: bytes,
    ) -> str: ...


class RQDocumentIndexQueue:
    def __init__(
        self,
        queue: Queue,
        *,
        job_timeout_seconds: int,
        result_ttl_seconds: int,
        failure_ttl_seconds: int,
    ) -> None:
        self._queue = queue
        self._job_timeout_seconds = job_timeout_seconds
        self._result_ttl_seconds = result_ttl_seconds
        self._failure_ttl_seconds = failure_ttl_seconds

    @classmethod
    def from_settings(cls) -> "RQDocumentIndexQueue":
        connection = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
        )
        queue = Queue(settings.document_index_queue_name, connection=connection)
        return cls(
            queue,
            job_timeout_seconds=settings.document_index_job_timeout_seconds,
            result_ttl_seconds=settings.document_index_result_ttl_seconds,
            failure_ttl_seconds=settings.document_index_failure_ttl_seconds,
        )

    async def enqueue_document_index_task(
        self,
        *,
        task_id: str,
        file_name: str,
        raw_data: bytes,
    ) -> str:
        return await asyncio.to_thread(
            self._enqueue_document_index_task_sync,
            task_id=task_id,
            file_name=file_name,
            raw_data=raw_data,
        )

    def _enqueue_document_index_task_sync(
        self,
        *,
        task_id: str,
        file_name: str,
        raw_data: bytes,
    ) -> str:
        job = self._queue.enqueue(
            run_document_index_task_job,
            kwargs={
                "task_id": task_id,
                "file_name": file_name,
                "raw_data": raw_data,
            },
            job_id=f"document-index-{task_id}",
            job_timeout=self._job_timeout_seconds,
            result_ttl=self._result_ttl_seconds,
            failure_ttl=self._failure_ttl_seconds,
        )
        return str(job.id)
