from fastapi.testclient import TestClient

from app.api.dependencies import get_embedding_client, get_llm_client, get_redis_store
from app.main import app
from app.models.document import DocumentSearchResult
from app.models.embedding import TextEmbedding
from app.services.llm_client import LLMChatResult, LLMConfigurationError


class FakeEmbeddingClient:
    async def embed_text(self, text: str) -> TextEmbedding:
        return TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4])


class FakeRedisStore:
    def __init__(self, results: list[DocumentSearchResult] | None = None) -> None:
        self.results = (
            results
            if results is not None
            else [
                DocumentSearchResult(
                    key="doc:abc:0",
                    content="Redis 用于 session、缓存和向量检索。",
                    metadata={"chunk_id": "abc:0", "source": "notes.md"},
                    distance=0.12,
                )
            ]
        )
        self.index_created = False

    async def ensure_vector_index(self, index_config=None) -> None:
        self.index_created = True

    async def search_document_chunks(
        self,
        query_embedding: list[float],
        *,
        top_k: int = 5,
        collection: str | None = None,
        index_config=None,
    ) -> list[DocumentSearchResult]:
        return self.results[:top_k]


class FakeLLMClient:
    def __init__(self) -> None:
        self.messages = []

    async def chat(self, **kwargs) -> LLMChatResult:
        self.messages = kwargs["messages"]
        return LLMChatResult(
            content="Redis 可以用于 session、缓存和向量检索。[1]",
            model=kwargs.get("model") or "mock-model",
            finish_reason="stop",
            usage={"total_tokens": 12},
        )


class FailingLLMClient:
    async def chat(self, **kwargs) -> LLMChatResult:
        raise LLMConfigurationError("LLM_API_KEY is not configured.")


def test_rag_query_returns_answer_with_sources() -> None:
    redis_store = FakeRedisStore()
    llm_client = FakeLLMClient()
    app.dependency_overrides[get_redis_store] = lambda: redis_store
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: llm_client
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/rag/query",
            json={"query": "Redis 能做什么？", "top_k": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Redis 可以用于 session、缓存和向量检索。[1]"
    assert body["model"] == "mock-model"
    assert body["finish_reason"] == "stop"
    assert body["usage"] == {"total_tokens": 12}
    assert body["sources"][0]["source_id"] == 1
    assert body["sources"][0]["metadata"]["source"] == "notes.md"
    assert redis_store.index_created is True
    assert llm_client.messages[0].role == "system"
    assert "[1] source=notes.md" in llm_client.messages[1].content
    assert "Redis 能做什么？" in llm_client.messages[1].content


def test_rag_query_returns_no_context_answer_without_calling_llm() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore(results=[])
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/rag/query",
            json={"query": "没有资料的问题", "top_k": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "answer": "我没有在知识库中检索到相关内容，无法基于已上传资料回答这个问题。",
        "model": None,
        "sources": [],
        "finish_reason": None,
        "usage": None,
    }


def test_rag_query_returns_503_when_llm_is_not_configured() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    app.dependency_overrides[get_embedding_client] = lambda: FakeEmbeddingClient()
    app.dependency_overrides[get_llm_client] = lambda: FailingLLMClient()
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v1/rag/query",
            json={"query": "Redis 能做什么？", "top_k": 1},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"] == "LLM_API_KEY is not configured."
