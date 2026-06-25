import asyncio
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.document import DocumentIndexTaskState
from app.rag.chunker import chunk_document
from app.rag.document_loader import (
    DocumentLoadError,
    UnsupportedDocumentTypeError,
    load_uploaded_document,
)
from app.core.runtime_config import load_runtime_config
from app.rag.indexer import index_document_chunks
from app.services.embedding_client import (
    EmbeddingClient,
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    build_embedding_client,
)
from app.services.redis_client import RedisStore


def create_document_index_task(file_name: str) -> DocumentIndexTaskState:
    now = _now_iso()
    safe_file_name = Path(file_name).name or "uploaded-document"
    return DocumentIndexTaskState(
        task_id=uuid4().hex,
        status="pending",
        file_name=safe_file_name,
        file_type=Path(safe_file_name).suffix.lower().lstrip(".") or None,
        created_at=now,
        updated_at=now,
    )


def classify_index_error(exc: Exception) -> tuple[str, bool]:
    """把索引失败归类为 (error_type, retryable)。

    transient（可重试）：上游 embedding provider 5xx / 网络抖动。
    permanent（不可重试）：文档格式/内容错误、embedding 配置缺失、其它校验错误。
    """
    if isinstance(exc, EmbeddingConfigurationError):
        return "configuration_error", False
    if isinstance(exc, EmbeddingProviderError):
        return "provider_transient_error", True
    if isinstance(exc, (UnsupportedDocumentTypeError, DocumentLoadError)):
        return "document_error", False
    if isinstance(exc, ValueError):
        return "validation_error", False
    return "unknown_error", False


async def run_document_index_task(
    *,
    task_id: str,
    file_name: str,
    raw_data: bytes,
    redis_store: RedisStore,
    embedding_client: EmbeddingClient,
) -> None:
    task = await redis_store.get_index_task(task_id)
    if task is None:
        task = create_document_index_task(file_name)
        task = task.model_copy(update={"task_id": task_id})

    if task.status == "done":
        return

    await redis_store.save_index_task(
        task.model_copy(update={"status": "running", "updated_at": _now_iso()})
    )

    try:
        document = load_uploaded_document(file_name, raw_data)
        chunks = chunk_document(document)
        indexed_keys = await index_document_chunks(
            chunks,
            embedding_client=embedding_client,
            redis_store=redis_store,
        )
        await redis_store.save_index_task(
            task.model_copy(
                update={
                    "status": "done",
                    "file_name": document.metadata.file_name,
                    "file_type": document.metadata.file_type,
                    "document_id": document.document_id,
                    "chunk_count": len(chunks),
                    "indexed_keys": indexed_keys,
                    "error_message": None,
                    "error_type": None,
                    "retryable": False,
                    "updated_at": _now_iso(),
                }
            )
        )
    except Exception as exc:
        error_type, retryable = classify_index_error(exc)
        await redis_store.save_index_task(
            task.model_copy(
                update={
                    "status": "failed",
                    "error_message": str(exc),
                    "error_type": error_type,
                    "retryable": retryable,
                    "updated_at": _now_iso(),
                }
            )
        )


def run_document_index_task_job(
    *,
    task_id: str,
    file_name: str,
    raw_data: bytes,
) -> None:
    asyncio.run(
        _run_document_index_task_job(
            task_id=task_id,
            file_name=file_name,
            raw_data=raw_data,
        )
    )


async def _run_document_index_task_job(
    *,
    task_id: str,
    file_name: str,
    raw_data: bytes,
) -> None:
    redis_store = RedisStore.from_settings()
    runtime_config = await load_runtime_config(redis_store)
    embedding_client = build_embedding_client(runtime_config.embedding)
    try:
        await run_document_index_task(
            task_id=task_id,
            file_name=file_name,
            raw_data=raw_data,
            redis_store=redis_store,
            embedding_client=embedding_client,
        )
    finally:
        await redis_store.aclose()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
