import json

import httpx
import pytest

from app.core.config import settings
from app.services.embedding_client import (
    DeterministicEmbeddingClient,
    EmbeddingConfigurationError,
    EmbeddingProviderError,
    OpenAICompatibleEmbeddingClient,
    build_embedding_client_from_settings,
)


@pytest.mark.anyio
async def test_deterministic_embedding_client_returns_expected_dimension() -> None:
    client = DeterministicEmbeddingClient(dimension=4)

    result = await client.embed_text("agent rag redis")

    assert result.text == "agent rag redis"
    assert len(result.embedding) == 4
    assert all(-1.0 <= value <= 1.0 for value in result.embedding)


@pytest.mark.anyio
async def test_deterministic_embedding_client_returns_stable_vectors() -> None:
    client = DeterministicEmbeddingClient(dimension=4)

    first = await client.embed_text("same text")
    second = await client.embed_text("same text")
    different = await client.embed_text("different text")

    assert first.embedding == second.embedding
    assert first.embedding != different.embedding


@pytest.mark.anyio
async def test_deterministic_embedding_client_rejects_empty_text() -> None:
    client = DeterministicEmbeddingClient(dimension=4)

    with pytest.raises(ValueError):
        await client.embed_text("")


@pytest.mark.anyio
async def test_openai_compatible_embedding_client_posts_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://example.test/v1/embeddings"
        assert request.headers["authorization"] == "Bearer test-key"
        assert json.loads(request.content) == {
            "model": "embedding-model",
            "input": ["hello", "world"],
        }
        return httpx.Response(
            200,
            json={
                "model": "embedding-model",
                "data": [
                    {"index": 1, "embedding": [0.3, 0.4]},
                    {"index": 0, "embedding": [0.1, 0.2]},
                ],
                "usage": {"total_tokens": 2},
            },
        )

    client = OpenAICompatibleEmbeddingClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="embedding-model",
        expected_dimension=2,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    results = await client.embed_texts(["hello", "world"])

    assert [result.text for result in results] == ["hello", "world"]
    assert [result.embedding for result in results] == [[0.1, 0.2], [0.3, 0.4]]


@pytest.mark.anyio
async def test_openai_compatible_embedding_client_can_request_dimensions() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {
            "model": "embedding-model",
            "input": ["hello"],
            "dimensions": 2,
        }
        return httpx.Response(
            200,
            json={
                "model": "embedding-model",
                "data": [{"index": 0, "embedding": [0.1, 0.2]}],
                "usage": {"total_tokens": 1},
            },
        )

    client = OpenAICompatibleEmbeddingClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="embedding-model",
        expected_dimension=2,
        dimensions=2,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await client.embed_text("hello")

    assert result.embedding == [0.1, 0.2]


@pytest.mark.anyio
async def test_openai_compatible_embedding_client_rejects_missing_api_key() -> None:
    client = OpenAICompatibleEmbeddingClient(
        base_url="https://example.test/v1",
        api_key="",
        model="embedding-model",
        expected_dimension=2,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))),
    )

    with pytest.raises(EmbeddingConfigurationError, match="EMBEDDING_API_KEY"):
        await client.embed_text("hello")


@pytest.mark.anyio
async def test_openai_compatible_embedding_client_wraps_provider_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"message": "invalid embedding key"}},
        )

    client = OpenAICompatibleEmbeddingClient(
        base_url="https://example.test/v1",
        api_key="bad-key",
        model="embedding-model",
        expected_dimension=2,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(EmbeddingProviderError, match="invalid embedding key"):
        await client.embed_text("hello")


@pytest.mark.anyio
async def test_openai_compatible_embedding_client_rejects_dimension_mismatch() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]},
        )

    client = OpenAICompatibleEmbeddingClient(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="embedding-model",
        expected_dimension=2,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(EmbeddingProviderError, match="dimension mismatch"):
        await client.embed_text("hello")


def test_get_embedding_client_defaults_to_fake_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")

    client = build_embedding_client_from_settings()

    assert isinstance(client, DeterministicEmbeddingClient)


def test_get_embedding_client_can_select_openai_compatible_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "openai-compatible")
    monkeypatch.setattr(settings, "embedding_api_key", "test-key")

    client = build_embedding_client_from_settings()

    assert isinstance(client, OpenAICompatibleEmbeddingClient)
