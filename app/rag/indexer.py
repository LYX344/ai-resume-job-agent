from app.models.document import DocumentChunk
from app.models.vector_index import RedisVectorIndexConfig
from app.services.embedding_client import EmbeddingClient
from app.services.redis_client import RedisStore


async def index_document_chunks(
    chunks: list[DocumentChunk],
    *,
    embedding_client: EmbeddingClient,
    redis_store: RedisStore,
    collection: str = "default",
    index_config: RedisVectorIndexConfig | None = None,
    ensure_index: bool = True,
) -> list[str]:
    if not chunks:
        return []

    if ensure_index:
        await redis_store.ensure_vector_index(index_config)

    embeddings = await embedding_client.embed_texts([chunk.content for chunk in chunks])
    keys: list[str] = []

    for chunk, embedding in zip(chunks, embeddings, strict=True):
        key = await redis_store.save_document_chunk(
            chunk,
            embedding.embedding,
            collection=collection,
            index_config=index_config,
        )
        keys.append(key)

    return keys
