from collections.abc import AsyncIterator

from fastapi import Depends

from app.core.runtime_config import load_runtime_config
from app.services.document_index_queue import DocumentIndexQueue, RQDocumentIndexQueue
from app.services.embedding_client import EmbeddingClient, build_embedding_client
from app.services.llm_client import OpenAICompatibleClient, build_llm_client
from app.services.mcp_client import MCPClient, build_mcp_client_from_settings
from app.services.mysql_client import MySQLStore
from app.services.redis_client import RedisStore
from app.services.rerank_client import RerankClient, build_rerank_client
from app.services.trace_store import TraceStore


async def get_redis_store() -> AsyncIterator[RedisStore]:
    store = RedisStore.from_settings()
    try:
        yield store
    finally:
        await store.aclose()


async def get_llm_client(
    redis_store: RedisStore = Depends(get_redis_store),
) -> AsyncIterator[OpenAICompatibleClient]:
    runtime_config = await load_runtime_config(redis_store)
    client = build_llm_client(runtime_config.llm)
    try:
        yield client
    finally:
        await client.aclose()


async def get_mysql_store() -> AsyncIterator[MySQLStore]:
    store = MySQLStore.from_settings()
    try:
        yield store
    finally:
        await store.aclose()


async def get_embedding_client(
    redis_store: RedisStore = Depends(get_redis_store),
) -> EmbeddingClient:
    runtime_config = await load_runtime_config(redis_store)
    return build_embedding_client(runtime_config.embedding)


async def get_rerank_client(
    redis_store: RedisStore = Depends(get_redis_store),
) -> RerankClient:
    runtime_config = await load_runtime_config(redis_store)
    return build_rerank_client(runtime_config.rerank)


def get_trace_store() -> TraceStore:
    return TraceStore.from_settings()


def get_document_index_queue() -> DocumentIndexQueue:
    return RQDocumentIndexQueue.from_settings()


def get_mcp_client() -> MCPClient:
    return build_mcp_client_from_settings()
