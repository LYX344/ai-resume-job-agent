import json

import httpx
import pytest

from app.models.document import DocumentSearchResult
from app.models.embedding import TextEmbedding
from app.rag.retriever import retrieve_document_chunks
from app.services.rerank_client import (
    IdentityRerankClient,
    OpenAICompatibleRerankClient,
    RerankConfigurationError,
    RerankedItem,
    RerankProviderError,
    build_rerank_client_from_settings,
)


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_identity_rerank_preserves_order_and_limits() -> None:
    client = IdentityRerankClient()

    items = await client.rerank("q", ["a", "b", "c"], top_n=2)

    assert [item.index for item in items] == [0, 1]


@pytest.mark.anyio
async def test_api_rerank_orders_by_relevance() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://x.test/v1/rerank"
        assert request.headers["authorization"] == "Bearer k"
        body = json.loads(request.content)
        assert body["query"] == "q"
        assert body["documents"] == ["a", "b", "c"]
        assert body["top_n"] == 2
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": 2, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.4},
                ]
            },
        )

    client = OpenAICompatibleRerankClient(
        base_url="https://x.test/v1",
        api_key="k",
        model="m",
        http_client=_mock_client(handler),
    )

    items = await client.rerank("q", ["a", "b", "c"], top_n=2)

    assert [item.index for item in items] == [2, 0]
    assert items[0].relevance_score == pytest.approx(0.9)


@pytest.mark.anyio
async def test_api_rerank_filters_out_of_range_index() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"index": 9, "relevance_score": 1.0}, {"index": 1, "relevance_score": 0.5}]},
        )

    client = OpenAICompatibleRerankClient(
        base_url="https://x.test/v1",
        api_key="k",
        model="m",
        http_client=_mock_client(handler),
    )

    items = await client.rerank("q", ["a", "b"], top_n=2)

    assert [item.index for item in items] == [1]


@pytest.mark.anyio
async def test_api_rerank_missing_key_raises() -> None:
    client = OpenAICompatibleRerankClient(
        base_url="https://x.test/v1",
        api_key="",
        model="m",
        http_client=_mock_client(lambda request: httpx.Response(200, json={"results": []})),
    )

    with pytest.raises(RerankConfigurationError):
        await client.rerank("q", ["a"], top_n=1)


@pytest.mark.anyio
async def test_api_rerank_http_error_raises() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    client = OpenAICompatibleRerankClient(
        base_url="https://x.test/v1",
        api_key="k",
        model="m",
        http_client=_mock_client(handler),
    )

    with pytest.raises(RerankProviderError):
        await client.rerank("q", ["a"], top_n=1)


def test_build_rerank_client_identity_by_default(monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "rerank_provider", "identity")

    assert isinstance(build_rerank_client_from_settings(), IdentityRerankClient)


def test_build_rerank_client_openai_compatible(monkeypatch) -> None:
    from app.core import config

    monkeypatch.setattr(config.settings, "rerank_provider", "openai-compatible")

    assert isinstance(build_rerank_client_from_settings(), OpenAICompatibleRerankClient)


class _FakeRerankRedis:
    def __init__(self, candidates: list[DocumentSearchResult]) -> None:
        self._candidates = candidates
        self.requested_top_k: int | None = None

    async def ensure_vector_index(self, index_config=None) -> None:
        return None

    async def search_document_chunks(
        self, query_embedding, *, top_k=5, collection=None, index_config=None
    ) -> list[DocumentSearchResult]:
        self.requested_top_k = top_k
        return self._candidates[:top_k]


class _FakeEmbedding:
    async def embed_text(self, text: str) -> TextEmbedding:
        return TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4])

    async def embed_texts(self, texts: list[str]) -> list[TextEmbedding]:
        return [TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4]) for text in texts]


class _ReverseRerank:
    async def rerank(self, query: str, documents: list[str], *, top_n=None) -> list[RerankedItem]:
        limit = len(documents) if top_n is None else min(top_n, len(documents))
        reversed_order = list(reversed(range(len(documents))))
        return [RerankedItem(index=index, relevance_score=1.0) for index in reversed_order[:limit]]


@pytest.mark.anyio
async def test_retrieve_with_rerank_reorders_and_limits() -> None:
    candidates = [
        DocumentSearchResult(key=f"doc:{i}", content=f"c{i}", metadata={}, distance=0.1 * i)
        for i in range(5)
    ]
    redis = _FakeRerankRedis(candidates)

    results = await retrieve_document_chunks(
        "q",
        top_k=2,
        embedding_client=_FakeEmbedding(),
        redis_store=redis,
        rerank_client=_ReverseRerank(),
        candidate_count=5,
    )

    assert redis.requested_top_k == 5
    assert [result.key for result in results] == ["doc:4", "doc:3"]


@pytest.mark.anyio
async def test_retrieve_without_rerank_uses_top_k_directly() -> None:
    candidates = [
        DocumentSearchResult(key=f"doc:{i}", content=f"c{i}", metadata={}, distance=0.1 * i)
        for i in range(5)
    ]
    redis = _FakeRerankRedis(candidates)

    results = await retrieve_document_chunks(
        "q",
        top_k=2,
        embedding_client=_FakeEmbedding(),
        redis_store=redis,
    )

    assert redis.requested_top_k == 2
    assert [result.key for result in results] == ["doc:0", "doc:1"]
