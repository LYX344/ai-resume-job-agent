import asyncio

from app.models.document import DocumentChunk, DocumentIndexTaskState
from app.models.embedding import TextEmbedding
from app.rag.document_loader import DocumentLoadError, UnsupportedDocumentTypeError
from app.services.embedding_client import (
    EmbeddingConfigurationError,
    EmbeddingProviderError,
)
from app.workers.document_indexing import (
    classify_index_error,
    create_document_index_task,
    run_document_index_task,
)


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.embed_texts_calls = 0

    async def embed_text(self, text: str) -> TextEmbedding:
        return TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4])

    async def embed_texts(self, texts: list[str]) -> list[TextEmbedding]:
        self.embed_texts_calls += 1
        return [TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4]) for text in texts]


class ProviderErrorEmbeddingClient:
    async def embed_text(self, text: str) -> TextEmbedding:
        raise EmbeddingProviderError("embedding provider returned HTTP 503")

    async def embed_texts(self, texts: list[str]) -> list[TextEmbedding]:
        raise EmbeddingProviderError("embedding provider returned HTTP 503")


class FakeRedisStore:
    def __init__(self) -> None:
        self.index_created = False
        self.saved_chunks: list[DocumentChunk] = []
        self.index_tasks: dict[str, DocumentIndexTaskState] = {}

    async def ensure_vector_index(self, index_config=None) -> None:
        self.index_created = True

    async def save_document_chunk(
        self,
        chunk: DocumentChunk,
        embedding: list[float],
        *,
        collection: str = "default",
        index_config=None,
    ) -> str:
        self.saved_chunks.append(chunk)
        return f"doc:{chunk.chunk_id}"

    async def save_index_task(self, task: DocumentIndexTaskState) -> None:
        self.index_tasks[task.task_id] = task

    async def get_index_task(self, task_id: str) -> DocumentIndexTaskState | None:
        return self.index_tasks.get(task_id)


def test_run_document_index_task_marks_task_done() -> None:
    asyncio.run(_run_document_index_task_marks_task_done())


async def _run_document_index_task_marks_task_done() -> None:
    redis_store = FakeRedisStore()
    embedding_client = FakeEmbeddingClient()
    task = create_document_index_task("notes.md")
    await redis_store.save_index_task(task)

    await run_document_index_task(
        task_id=task.task_id,
        file_name="notes.md",
        raw_data=b"# Notes\n\nRedis RAG Agent",
        redis_store=redis_store,
        embedding_client=embedding_client,
    )

    finished_task = redis_store.index_tasks[task.task_id]
    assert finished_task.status == "done"
    assert finished_task.file_name == "notes.md"
    assert finished_task.file_type == "md"
    assert finished_task.chunk_count == 1
    assert finished_task.indexed_keys == [f"doc:{finished_task.document_id}:0"]
    assert finished_task.error_message is None
    assert finished_task.error_type is None
    assert finished_task.retryable is False
    assert embedding_client.embed_texts_calls == 1
    assert redis_store.index_created is True
    assert redis_store.saved_chunks[0].content == "# Notes\n\nRedis RAG Agent"


def test_run_document_index_task_marks_task_failed_for_invalid_file_type() -> None:
    asyncio.run(_run_document_index_task_marks_task_failed_for_invalid_file_type())


async def _run_document_index_task_marks_task_failed_for_invalid_file_type() -> None:
    redis_store = FakeRedisStore()
    task = create_document_index_task("slides.pptx")
    await redis_store.save_index_task(task)

    await run_document_index_task(
        task_id=task.task_id,
        file_name="slides.pptx",
        raw_data=b"fake pptx",
        redis_store=redis_store,
        embedding_client=FakeEmbeddingClient(),
    )

    failed_task = redis_store.index_tasks[task.task_id]
    assert failed_task.status == "failed"
    assert "Unsupported document type" in str(failed_task.error_message)
    assert failed_task.error_type == "document_error"
    assert failed_task.retryable is False
    assert failed_task.chunk_count == 0
    assert failed_task.indexed_keys == []
    assert redis_store.saved_chunks == []


def test_run_document_index_task_is_idempotent_when_already_done() -> None:
    asyncio.run(_run_document_index_task_is_idempotent_when_already_done())


async def _run_document_index_task_is_idempotent_when_already_done() -> None:
    redis_store = FakeRedisStore()
    embedding_client = FakeEmbeddingClient()
    task = create_document_index_task("notes.md").model_copy(
        update={"status": "done", "document_id": "doc123", "chunk_count": 1}
    )
    await redis_store.save_index_task(task)

    await run_document_index_task(
        task_id=task.task_id,
        file_name="notes.md",
        raw_data=b"# Notes\n\nRedis RAG Agent",
        redis_store=redis_store,
        embedding_client=embedding_client,
    )

    assert embedding_client.embed_texts_calls == 0
    assert redis_store.saved_chunks == []
    assert redis_store.index_tasks[task.task_id].status == "done"


def test_run_document_index_task_marks_transient_provider_error_retryable() -> None:
    asyncio.run(_run_document_index_task_marks_transient_provider_error_retryable())


async def _run_document_index_task_marks_transient_provider_error_retryable() -> None:
    redis_store = FakeRedisStore()
    task = create_document_index_task("notes.md")
    await redis_store.save_index_task(task)

    await run_document_index_task(
        task_id=task.task_id,
        file_name="notes.md",
        raw_data=b"# Notes\n\nRedis RAG Agent",
        redis_store=redis_store,
        embedding_client=ProviderErrorEmbeddingClient(),
    )

    failed_task = redis_store.index_tasks[task.task_id]
    assert failed_task.status == "failed"
    assert failed_task.error_type == "provider_transient_error"
    assert failed_task.retryable is True
    assert redis_store.saved_chunks == []


def test_classify_index_error_distinguishes_permanent_and_transient() -> None:
    assert classify_index_error(EmbeddingProviderError("5xx")) == (
        "provider_transient_error",
        True,
    )
    assert classify_index_error(EmbeddingConfigurationError("no key")) == (
        "configuration_error",
        False,
    )
    assert classify_index_error(UnsupportedDocumentTypeError("pdf")) == (
        "document_error",
        False,
    )
    assert classify_index_error(DocumentLoadError("empty")) == (
        "document_error",
        False,
    )
    assert classify_index_error(ValueError("bad")) == ("validation_error", False)
    assert classify_index_error(RuntimeError("boom")) == ("unknown_error", False)
