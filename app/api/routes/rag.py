from fastapi import APIRouter, Depends, HTTPException
from redis import RedisError

from app.api.dependencies import (
    get_embedding_client,
    get_llm_client,
    get_redis_store,
    get_rerank_client,
)
from app.core.config import settings
from app.models.rag import RagQueryRequest, RagQueryResponse
from app.rag.answerer import answer_rag_query
from app.rag.query_rewriter import build_query_rewriter
from app.services.embedding_client import (
    EmbeddingClient,
    EmbeddingClientError,
    EmbeddingConfigurationError,
)
from app.services.llm_client import LLMClientError, LLMConfigurationError, OpenAICompatibleClient
from app.services.redis_client import RedisStore
from app.services.rerank_client import RerankClient

router = APIRouter(tags=["rag"])


@router.post("/rag/query", response_model=RagQueryResponse)
async def rag_query(
    request: RagQueryRequest,
    redis_store: RedisStore = Depends(get_redis_store),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    llm_client: OpenAICompatibleClient = Depends(get_llm_client),
    rerank_client: RerankClient = Depends(get_rerank_client),
) -> RagQueryResponse:
    query_rewriter = build_query_rewriter(llm_client) if request.rewrite else None
    try:
        return await answer_rag_query(
            request.query,
            top_k=request.top_k,
            embedding_client=embedding_client,
            redis_store=redis_store,
            llm_client=llm_client,
            model=request.model,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            collection=request.collection,
            rerank_client=rerank_client,
            candidate_count=settings.rerank_candidate_count,
            query_rewriter=query_rewriter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=502, detail=f"Redis search failed: {exc}") from exc
    except EmbeddingConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmbeddingClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
