from io import BytesIO

import pymupdf
from docx import Document as DocxDocument
from fastapi.testclient import TestClient

from app.api.dependencies import get_document_index_queue, get_embedding_client, get_redis_store
from app.main import app
from app.models.document import DocumentChunk, DocumentIndexTaskState, DocumentSearchResult
from app.models.embedding import TextEmbedding


class FakeEmbeddingClient:
    async def embed_text(self, text: str) -> TextEmbedding:
        return TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4])

    async def embed_texts(self, texts: list[str]) -> list[TextEmbedding]:
        return [TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4]) for text in texts]


class FakeRedisStore:
    def __init__(self) -> None:
        self.index_created = False
        self.saved_chunks: list[DocumentChunk] = []
        self.saved_collections: list[str] = []
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
        self.saved_collections.append(collection)
        return f"doc:{chunk.chunk_id}"

    async def save_index_task(self, task: DocumentIndexTaskState) -> None:
        self.index_tasks[task.task_id] = task

    async def get_index_task(self, task_id: str) -> DocumentIndexTaskState | None:
        return self.index_tasks.get(task_id)

    async def search_document_chunks(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        collection: str | None = None,
        index_config=None,
    ) -> list[DocumentSearchResult]:
        return [
            DocumentSearchResult(
                key="doc:abc:0",
                content="Redis RAG Agent",
                metadata={"chunk_id": "abc:0", "source": "notes.md"},
                distance=0.12,
            )
        ][:top_k]


class FakeDocumentIndexQueue:
    def __init__(self) -> None:
        self.enqueued_tasks: list[dict[str, object]] = []

    async def enqueue_document_index_task(
        self,
        *,
        task_id: str,
        file_name: str,
        raw_data: bytes,
    ) -> str:
        self.enqueued_tasks.append(
            {
                "task_id": task_id,
                "file_name": file_name,
                "raw_data": raw_data,
            }
        )
        return f"document-index:{task_id}"


class FailingDocumentIndexQueue:
    async def enqueue_document_index_task(
        self,
        *,
        task_id: str,
        file_name: str,
        raw_data: bytes,
    ) -> str:
        raise RuntimeError("queue unavailable")


def test_upload_markdown_document_indexes_chunks() -> None:
    redis_store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("notes.md", b"# Notes\n\nRedis RAG Agent", "text/markdown")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["file_name"] == "notes.md"
    assert body["file_type"] == "md"
    assert body["chunk_count"] == 1
    assert body["indexed_keys"] == [f"doc:{body['document_id']}:0"]
    assert redis_store.index_created is True
    assert redis_store.saved_chunks[0].content == "# Notes\n\nRedis RAG Agent"


def test_upload_docx_document_indexes_chunks() -> None:
    redis_store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    client = TestClient(app)
    docx_data = _build_docx_bytes("简历项目", "AI Resume Job Agent 支持 DOCX 入库。")

    try:
        response = client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "resume.docx",
                    docx_data,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["file_name"] == "resume.docx"
    assert body["file_type"] == "docx"
    assert body["chunk_count"] == 1
    assert redis_store.index_created is True
    assert "AI Resume Job Agent 支持 DOCX 入库。" in redis_store.saved_chunks[0].content


def test_upload_document_async_creates_task_and_enqueues_index_job() -> None:
    redis_store = FakeRedisStore()
    index_queue = FakeDocumentIndexQueue()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_document_index_queue] = lambda: index_queue
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/documents/upload/async",
            files={"file": ("notes.md", b"# Notes\n\nRedis RAG Agent", "text/markdown")},
        )
        task_id = response.json()["task_id"]
        status_response = client.get(f"/api/v1/documents/tasks/{task_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["file_name"] == "notes.md"
    assert index_queue.enqueued_tasks == [
        {
            "task_id": task_id,
            "file_name": "notes.md",
            "raw_data": b"# Notes\n\nRedis RAG Agent",
        }
    ]
    assert redis_store.index_created is False
    assert redis_store.saved_chunks == []
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["task_id"] == task_id
    assert status_body["status"] == "pending"
    assert status_body["file_name"] == "notes.md"
    assert status_body["file_type"] == "md"
    assert status_body["chunk_count"] == 0
    assert status_body["indexed_keys"] == []
    assert status_body["error_message"] is None


def test_upload_document_async_enqueues_unsupported_file_type_for_worker_validation() -> None:
    redis_store = FakeRedisStore()
    index_queue = FakeDocumentIndexQueue()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_document_index_queue] = lambda: index_queue
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/documents/upload/async",
            files={
                "file": (
                    "slides.pptx",
                    b"fake pptx",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
        )
        task_id = response.json()["task_id"]
        status_response = client.get(f"/api/v1/documents/tasks/{task_id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    assert status_response.status_code == 200
    status_body = status_response.json()
    assert status_body["status"] == "pending"
    assert status_body["file_type"] == "pptx"
    assert index_queue.enqueued_tasks[0]["file_name"] == "slides.pptx"
    assert redis_store.saved_chunks == []


def test_upload_document_async_records_failed_task_when_enqueue_fails() -> None:
    redis_store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_document_index_queue] = lambda: FailingDocumentIndexQueue()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/documents/upload/async",
            files={"file": ("notes.md", b"# Notes", "text/markdown")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert "Document index enqueue failed" in response.json()["detail"]
    task = next(iter(redis_store.index_tasks.values()))
    assert task.status == "failed"
    assert task.error_message == "queue unavailable"


def test_get_document_index_task_returns_404_for_missing_task() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    client = TestClient(app)

    try:
        response = client.get("/api/v1/documents/tasks/missing")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"] == "Document index task not found."


def test_upload_document_rejects_unsupported_file_type() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/documents/upload",
            files={
                "file": (
                    "slides.pptx",
                    b"fake pptx",
                    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                )
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Unsupported document type" in response.json()["detail"]


def test_upload_text_layer_pdf_document_indexes_chunks() -> None:
    redis_store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    client = TestClient(app)
    pdf_data = _build_text_pdf_bytes("Resume RAG Agent FastAPI Redis Project")

    try:
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("resume.pdf", pdf_data, "application/pdf")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["file_name"] == "resume.pdf"
    assert body["file_type"] == "pdf"
    assert body["chunk_count"] >= 1
    assert redis_store.index_created is True
    assert "Resume RAG Agent" in redis_store.saved_chunks[0].content


def test_upload_document_rejects_empty_file() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/documents/upload",
            files={"file": ("empty.txt", b"   ", "text/plain")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 400
    assert "Document is empty" in response.json()["detail"]


def test_search_documents_returns_matching_chunks() -> None:
    redis_store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/documents/search",
            json={"query": "Redis RAG", "top_k": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "query": "Redis RAG",
        "top_k": 1,
        "results": [
            {
                "key": "doc:abc:0",
                "content": "Redis RAG Agent",
                "metadata": {"chunk_id": "abc:0", "source": "notes.md"},
                "distance": 0.12,
            }
        ],
    }
    assert redis_store.index_created is True


def test_search_documents_rejects_invalid_top_k() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/documents/search",
            json={"query": "Redis RAG", "top_k": 0},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def _build_docx_bytes(*paragraphs: str) -> bytes:
    document = DocxDocument()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _build_text_pdf_bytes(text: str) -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=14)
    data = document.tobytes()
    document.close()
    return data
