import asyncio

from app.models.document import DocumentSearchResult
from app.models.embedding import TextEmbedding
from app.tools.search_docs import search_docs


class FakeEmbeddingClient:
    async def embed_text(self, text: str) -> TextEmbedding:
        return TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4])


class FakeRedisStore:
    def __init__(self) -> None:
        self.index_created = False
        self.query_embedding: list[float] | None = None

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
        self.query_embedding = query_embedding
        return [
            DocumentSearchResult(
                key="doc:abc:0",
                content="search_docs 会返回可引用的知识库片段。",
                metadata={"chunk_id": "abc:0", "source": "tools.md"},
                distance=0.07,
            )
        ][:top_k]


def test_search_docs_returns_rag_sources() -> None:
    redis_store = FakeRedisStore()

    sources = asyncio.run(
        search_docs(
            "工具节点是什么？",
            top_k=1,
            embedding_client=FakeEmbeddingClient(),
            redis_store=redis_store,
        )
    )

    assert redis_store.index_created is True
    assert redis_store.query_embedding == [0.1, 0.2, 0.3, 0.4]
    assert len(sources) == 1
    assert sources[0].source_id == 1
    assert sources[0].key == "doc:abc:0"
    assert sources[0].metadata["source"] == "tools.md"
