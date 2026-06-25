from types import SimpleNamespace

import pytest

from app.models.document import DocumentSearchResult
from app.models.embedding import TextEmbedding
from app.rag.query_rewriter import (
    IdentityQueryRewriter,
    LLMQueryRewriter,
    build_query_rewriter,
)
from app.rag.retriever import retrieve_document_chunks
from app.services.llm_client import LLMProviderError


class FakeLLM:
    def __init__(self, content: str = "改写后的查询", error: Exception | None = None) -> None:
        self._content = content
        self._error = error

    async def chat(self, *, messages, model=None, temperature=None, max_tokens=None):
        if self._error is not None:
            raise self._error
        return SimpleNamespace(content=self._content)


@pytest.mark.anyio
async def test_identity_rewriter_returns_original() -> None:
    assert await IdentityQueryRewriter().rewrite("它怎么做的") == "它怎么做的"


@pytest.mark.anyio
async def test_llm_rewriter_rewrites_query() -> None:
    rewriter = LLMQueryRewriter(FakeLLM(content="项目里 Redis 的作用"))
    assert await rewriter.rewrite("它怎么用的") == "项目里 Redis 的作用"


@pytest.mark.anyio
async def test_llm_rewriter_degrades_on_llm_error() -> None:
    rewriter = LLMQueryRewriter(FakeLLM(error=LLMProviderError("boom")))
    assert await rewriter.rewrite("原始问题") == "原始问题"


@pytest.mark.anyio
async def test_llm_rewriter_degrades_on_empty_output() -> None:
    rewriter = LLMQueryRewriter(FakeLLM(content="   "))
    assert await rewriter.rewrite("原始问题") == "原始问题"


@pytest.mark.anyio
async def test_llm_rewriter_degrades_on_overlong_output() -> None:
    rewriter = LLMQueryRewriter(FakeLLM(content="我们需要把这个问题改写成更适合检索的查询。" * 10))
    assert await rewriter.rewrite("啥时候到岗") == "啥时候到岗"


def test_build_query_rewriter_selects_provider() -> None:
    assert isinstance(build_query_rewriter(FakeLLM(), provider="llm"), LLMQueryRewriter)
    assert isinstance(build_query_rewriter(FakeLLM(), provider="identity"), IdentityQueryRewriter)


class _CaptureEmbedding:
    def __init__(self) -> None:
        self.embedded_text: str | None = None

    async def embed_text(self, text: str) -> TextEmbedding:
        self.embedded_text = text
        return TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4])

    async def embed_texts(self, texts: list[str]) -> list[TextEmbedding]:
        return [TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4]) for text in texts]


class _FakeRedis:
    async def ensure_vector_index(self, index_config=None) -> None:
        return None

    async def search_document_chunks(
        self, query_embedding, *, top_k=5, collection=None, index_config=None
    ) -> list[DocumentSearchResult]:
        return [DocumentSearchResult(key="doc:0", content="c", metadata={}, distance=0.1)][:top_k]


class _StubRewriter:
    async def rewrite(self, query: str) -> str:
        return f"REWRITTEN:{query}"


@pytest.mark.anyio
async def test_retrieve_uses_rewritten_query_for_embedding() -> None:
    embedding = _CaptureEmbedding()

    results = await retrieve_document_chunks(
        "原问题",
        top_k=1,
        embedding_client=embedding,
        redis_store=_FakeRedis(),
        query_rewriter=_StubRewriter(),
    )

    assert embedding.embedded_text == "REWRITTEN:原问题"
    assert len(results) == 1
