from app.models.chat import ChatMessage
from app.models.document import DocumentSearchResult
from app.models.rag import RagQueryResponse, RagSource
from app.models.vector_index import RedisVectorIndexConfig
from app.rag.query_rewriter import QueryRewriter
from app.rag.retriever import retrieve_document_chunks
from app.services.embedding_client import EmbeddingClient
from app.services.llm_client import OpenAICompatibleClient
from app.services.redis_client import RedisStore
from app.services.rerank_client import RerankClient


NO_CONTEXT_ANSWER = "我没有在知识库中检索到相关内容，无法基于已上传资料回答这个问题。"


async def answer_rag_query(
    query: str,
    *,
    top_k: int,
    embedding_client: EmbeddingClient,
    redis_store: RedisStore,
    llm_client: OpenAICompatibleClient,
    model: str | None = None,
    temperature: float | None = 0.2,
    max_tokens: int | None = None,
    collection: str | None = None,
    rerank_client: RerankClient | None = None,
    candidate_count: int | None = None,
    query_rewriter: QueryRewriter | None = None,
    index_config: RedisVectorIndexConfig | None = None,
) -> RagQueryResponse:
    chunks = await retrieve_document_chunks(
        query,
        top_k=top_k,
        embedding_client=embedding_client,
        redis_store=redis_store,
        collection=collection,
        rerank_client=rerank_client,
        candidate_count=candidate_count,
        query_rewriter=query_rewriter,
        index_config=index_config,
    )
    sources = to_rag_sources(chunks)
    return await answer_from_sources(
        query,
        sources=sources,
        llm_client=llm_client,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def answer_from_sources(
    query: str,
    *,
    sources: list[RagSource],
    llm_client: OpenAICompatibleClient,
    memory_context: str = "",
    model: str | None = None,
    temperature: float | None = 0.2,
    max_tokens: int | None = None,
) -> RagQueryResponse:
    if not sources:
        return RagQueryResponse(answer=NO_CONTEXT_ANSWER, sources=[])

    result = await llm_client.chat(
        messages=build_rag_messages(query, sources, memory_context=memory_context),
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return RagQueryResponse(
        answer=result.content,
        model=result.model,
        sources=sources,
        finish_reason=result.finish_reason,
        usage=result.usage,
    )


def build_rag_messages(
    query: str,
    sources: list[RagSource],
    *,
    memory_context: str = "",
) -> list[ChatMessage]:
    memory_instruction = (
        f"可参考以下用户偏好和项目背景，但不能把它当作知识库引用来源：\n{memory_context}"
        if memory_context
        else ""
    )
    return [
        ChatMessage(
            role="system",
            content=(
                "你是一个个人知识库 RAG 助手。只能基于提供的上下文回答。"
                "如果上下文不足以回答问题，直接说明不知道，不能编造。"
                "回答中需要用 [1]、[2] 这样的编号标注引用来源。"
                f"{memory_instruction}"
            ),
        ),
        ChatMessage(
            role="user",
            content=f"问题：{query}\n\n上下文：\n{_format_context(sources)}",
        ),
    ]


def to_rag_sources(chunks: list[DocumentSearchResult]) -> list[RagSource]:
    return [
        RagSource(
            source_id=index + 1,
            key=chunk.key,
            content=chunk.content,
            metadata=chunk.metadata,
            distance=chunk.distance,
        )
        for index, chunk in enumerate(chunks)
    ]


def _format_context(sources: list[RagSource]) -> str:
    return "\n\n".join(
        f"[{source.source_id}] source={source.metadata.get('source', source.key)}\n{source.content}"
        for source in sources
    )
