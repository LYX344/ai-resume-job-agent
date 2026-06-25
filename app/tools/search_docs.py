from app.models.rag import RagSource
from app.models.vector_index import RedisVectorIndexConfig
from app.rag.answerer import to_rag_sources
from app.rag.retriever import retrieve_document_chunks
from app.services.embedding_client import EmbeddingClient
from app.services.redis_client import RedisStore


async def search_docs(
    query: str,
    *,
    top_k: int,
    embedding_client: EmbeddingClient,
    redis_store: RedisStore,
    index_config: RedisVectorIndexConfig | None = None,
) -> list[RagSource]:
    chunks = await retrieve_document_chunks(
        query,
        top_k=top_k,
        embedding_client=embedding_client,
        redis_store=redis_store,
        index_config=index_config,
    )
    return to_rag_sources(chunks)
