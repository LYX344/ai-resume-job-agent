"""Rerank client abstraction for two-stage RAG retrieval.

Two-stage retrieval: vector search recalls a larger candidate set, then a
cross-encoder reranker reorders them by query relevance and keeps top_k. This
improves precision over pure vector similarity, which is a high-frequency RAG
interview point.

Providers:
- ``OpenAICompatibleRerankClient``: calls an OpenAI-compatible ``/rerank``
  endpoint (e.g. SiliconFlow BAAI/bge-reranker-v2-m3).
- ``IdentityRerankClient``: keeps the original order (no-op). Used when rerank
  is disabled or no key is configured, so the pipeline degrades gracefully.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.config import settings
from app.models.config import ModelRuntimeConfig


@dataclass(frozen=True)
class RerankedItem:
    index: int
    relevance_score: float


class RerankClient(Protocol):
    async def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[RerankedItem]: ...


class RerankClientError(Exception):
    """Base error for rerank client failures."""


class RerankConfigurationError(RerankClientError):
    """Raised when required rerank configuration is missing."""


class RerankProviderError(RerankClientError):
    """Raised when the upstream rerank provider returns an error."""


class IdentityRerankClient:
    """No-op reranker that preserves the original candidate order."""

    name = "identity"

    async def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[RerankedItem]:
        limit = len(documents) if top_n is None else min(top_n, len(documents))
        return [RerankedItem(index=index, relevance_score=0.0) for index in range(limit)]


class OpenAICompatibleRerankClient:
    name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._client = http_client

    @classmethod
    def from_settings(cls) -> "OpenAICompatibleRerankClient":
        return cls(
            base_url=settings.rerank_base_url,
            api_key=settings.rerank_api_key,
            model=settings.rerank_model,
            timeout_seconds=settings.rerank_timeout_seconds,
        )

    async def rerank(
        self, query: str, documents: list[str], *, top_n: int | None = None
    ) -> list[RerankedItem]:
        if not documents:
            return []
        payload: dict[str, Any] = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "return_documents": False,
        }
        if top_n is not None:
            payload["top_n"] = min(top_n, len(documents))

        data = await self._post_json(payload)
        return self._parse_rerank_response(data, candidate_count=len(documents))

    @property
    def _rerank_url(self) -> str:
        return f"{self.base_url}/rerank"

    @property
    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RerankConfigurationError("RERANK_API_KEY is not configured.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            if self._client is not None:
                response = await self._client.post(
                    self._rerank_url, headers=self._headers, json=payload
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(
                        self._rerank_url, headers=self._headers, json=payload
                    )
        except httpx.RequestError as exc:
            raise RerankProviderError(f"Rerank provider request failed: {exc}") from exc

        if response.status_code >= 400:
            message = response.text
            try:
                message = response.json().get("error", {}).get("message", message)
            except ValueError:
                pass
            raise RerankProviderError(
                f"Rerank provider returned HTTP {response.status_code}: {message}"
            )
        return response.json()

    def _parse_rerank_response(
        self, data: dict[str, Any], *, candidate_count: int
    ) -> list[RerankedItem]:
        try:
            results = data["results"]
        except (KeyError, TypeError) as exc:
            raise RerankProviderError(
                "Rerank provider returned an invalid response shape."
            ) from exc

        items: list[RerankedItem] = []
        for entry in results:
            try:
                index = int(entry["index"])
                score = float(entry.get("relevance_score", entry.get("score", 0.0)))
            except (KeyError, TypeError, ValueError) as exc:
                raise RerankProviderError(
                    "Rerank provider returned an invalid result entry."
                ) from exc
            if 0 <= index < candidate_count:
                items.append(RerankedItem(index=index, relevance_score=score))
        return items


def build_rerank_client(config: ModelRuntimeConfig | None = None) -> RerankClient:
    """按运行时配置构建重排 client；缺省字段回退 `.env` 默认。"""
    config = config or ModelRuntimeConfig()
    provider = (config.provider or settings.rerank_provider or "identity").lower()
    if provider in {"identity", "none", ""}:
        return IdentityRerankClient()
    if provider in {"openai", "openai-compatible"}:
        return OpenAICompatibleRerankClient(
            base_url=config.base_url or settings.rerank_base_url,
            api_key=config.api_key or settings.rerank_api_key,
            model=config.model or settings.rerank_model,
            timeout_seconds=settings.rerank_timeout_seconds,
        )
    raise ValueError(f"Unsupported RERANK_PROVIDER: {provider}")


def build_rerank_client_from_settings() -> RerankClient:
    return build_rerank_client(None)
