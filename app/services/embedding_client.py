from hashlib import sha256
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.models.config import ModelRuntimeConfig
from app.models.embedding import TextEmbedding


class EmbeddingClient(Protocol):
    async def embed_text(self, text: str) -> TextEmbedding: ...

    async def embed_texts(self, texts: list[str]) -> list[TextEmbedding]: ...


class EmbeddingClientError(Exception):
    """Base error for embedding client failures."""


class EmbeddingConfigurationError(EmbeddingClientError):
    """Raised when required embedding configuration is missing."""


class EmbeddingProviderError(EmbeddingClientError):
    """Raised when the upstream embedding provider returns an error."""


class DeterministicEmbeddingClient:
    def __init__(self, dimension: int | None = None) -> None:
        self.dimension = dimension or settings.redis_vector_dimension
        if self.dimension <= 0:
            raise ValueError("dimension must be greater than 0")

    async def embed_text(self, text: str) -> TextEmbedding:
        if not text:
            raise ValueError("text must not be empty")
        return TextEmbedding(text=text, embedding=self._build_vector(text))

    async def embed_texts(self, texts: list[str]) -> list[TextEmbedding]:
        return [await self.embed_text(text) for text in texts]

    def _build_vector(self, text: str) -> list[float]:
        values: list[float] = []
        block_index = 0

        while len(values) < self.dimension:
            digest = sha256(f"{block_index}:{text}".encode("utf-8")).digest()
            values.extend((byte / 127.5) - 1.0 for byte in digest)
            block_index += 1

        return values[: self.dimension]


class OpenAICompatibleEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        expected_dimension: int,
        dimensions: int | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 1,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.expected_dimension = expected_dimension
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._client = http_client

    @classmethod
    def from_settings(cls) -> "OpenAICompatibleEmbeddingClient":
        return cls(
            base_url=settings.embedding_base_url,
            api_key=settings.embedding_api_key,
            model=settings.embedding_model,
            expected_dimension=settings.redis_vector_dimension,
            dimensions=settings.embedding_dimensions or None,
            timeout_seconds=settings.embedding_timeout_seconds,
            max_retries=settings.embedding_max_retries,
        )

    async def embed_text(self, text: str) -> TextEmbedding:
        return (await self.embed_texts([text]))[0]

    async def embed_texts(self, texts: list[str]) -> list[TextEmbedding]:
        if not texts:
            return []
        if any(not text for text in texts):
            raise ValueError("text must not be empty")

        payload = {
            "model": self.model,
            "input": texts,
        }
        if self.dimensions is not None:
            payload["dimensions"] = self.dimensions
        data = await self._post_json(payload)
        embeddings = self._parse_embedding_response(data, expected_count=len(texts))
        return [
            TextEmbedding(text=text, embedding=embedding)
            for text, embedding in zip(texts, embeddings, strict=True)
        ]

    @property
    def _embeddings_url(self) -> str:
        return f"{self.base_url}/embeddings"

    @property
    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise EmbeddingConfigurationError("EMBEDDING_API_KEY is not configured.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        attempts = max(0, self.max_retries) + 1

        for attempt in range(attempts):
            try:
                response = await self._post(payload)
                if response.status_code >= 500 and attempt < attempts - 1:
                    continue
                self._raise_for_status(response)
                return response.json()
            except httpx.RequestError as exc:
                last_error = exc
                if attempt == attempts - 1:
                    break

        raise EmbeddingProviderError(
            f"Embedding provider request failed: {last_error}"
        ) from last_error

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(
                self._embeddings_url,
                headers=self._headers,
                json=payload,
            )

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            return await client.post(
                self._embeddings_url,
                headers=self._headers,
                json=payload,
            )

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return

        message = response.text
        try:
            data = response.json()
            message = data.get("error", {}).get("message", message)
        except ValueError:
            pass
        raise EmbeddingProviderError(
            f"Embedding provider returned HTTP {response.status_code}: {message}"
        )

    def _parse_embedding_response(
        self,
        data: dict[str, Any],
        *,
        expected_count: int,
    ) -> list[list[float]]:
        try:
            items = data["data"]
            if len(items) != expected_count:
                raise ValueError("unexpected embedding count")
            if all("index" in item for item in items):
                items = sorted(items, key=lambda item: item["index"])
            embeddings = [item["embedding"] for item in items]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingProviderError(
                "Embedding provider returned an invalid embedding response."
            ) from exc

        for embedding in embeddings:
            if not isinstance(embedding, list) or not embedding:
                raise EmbeddingProviderError(
                    "Embedding provider returned an invalid embedding vector."
                )
            if len(embedding) != self.expected_dimension:
                raise EmbeddingProviderError(
                    "Embedding dimension mismatch: "
                    f"expected {self.expected_dimension}, got {len(embedding)}."
                )
            if not all(isinstance(value, int | float) for value in embedding):
                raise EmbeddingProviderError(
                    "Embedding provider returned non-numeric embedding values."
                )

        return [[float(value) for value in embedding] for embedding in embeddings]


def build_embedding_client(config: ModelRuntimeConfig | None = None) -> EmbeddingClient:
    """按运行时配置构建向量化 client；缺省字段回退 `.env` 默认。"""
    config = config or ModelRuntimeConfig()
    provider = (config.provider or settings.embedding_provider).lower()
    if provider == "fake":
        return DeterministicEmbeddingClient()
    if provider in {"openai", "openai-compatible"}:
        return OpenAICompatibleEmbeddingClient(
            base_url=config.base_url or settings.embedding_base_url,
            api_key=config.api_key or settings.embedding_api_key,
            model=config.model or settings.embedding_model,
            expected_dimension=settings.redis_vector_dimension,
            dimensions=(config.dimensions or settings.embedding_dimensions) or None,
            timeout_seconds=settings.embedding_timeout_seconds,
            max_retries=settings.embedding_max_retries,
        )
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}")


def build_embedding_client_from_settings() -> EmbeddingClient:
    return build_embedding_client(None)
