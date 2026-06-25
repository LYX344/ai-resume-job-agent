from app.models.document import DocumentSearchResult
from app.models.vector_index import RedisVectorIndexConfig
from app.services.embedding_client import EmbeddingClient
from app.services.redis_client import RedisStore
from app.rag.query_rewriter import QueryRewriter
from app.services.rerank_client import RerankClient


async def retrieve_document_chunks(
    query: str,
    *,
    top_k: int,
    embedding_client: EmbeddingClient,
    redis_store: RedisStore,
    collection: str | None = None,
    rerank_client: RerankClient | None = None,
    candidate_count: int | None = None,
    query_rewriter: QueryRewriter | None = None,
    index_config: RedisVectorIndexConfig | None = None,
) -> list[DocumentSearchResult]:
    search_query = query
    if query_rewriter is not None:
        search_query = await query_rewriter.rewrite(query)
    embedding = await embedding_client.embed_text(search_query)
    await redis_store.ensure_vector_index(index_config)

    if rerank_client is None:
        return await redis_store.search_document_chunks(
            embedding.embedding,
            top_k=top_k,
            collection=collection,
            index_config=index_config,
        )

    recall_count = max(top_k, candidate_count or top_k)
    candidates = await redis_store.search_document_chunks(
        embedding.embedding,
        top_k=recall_count,
        collection=collection,
        index_config=index_config,
    )
    if not candidates:
        return []

    ranked = await rerank_client.rerank(
        query, [candidate.content for candidate in candidates], top_n=top_k
    )
    reranked = [
        candidates[item.index] for item in ranked if 0 <= item.index < len(candidates)
    ]
    return reranked[:top_k]
