from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from redis import RedisError

from app.api.dependencies import (
    get_document_index_queue,
    get_embedding_client,
    get_llm_client,
    get_redis_store,
    get_rerank_client,
)
from app.core.config import settings
from app.rag.query_rewriter import build_query_rewriter
from app.services.llm_client import OpenAICompatibleClient
from app.models.document import (
    DocumentIndexTaskState,
    DocumentIngestResponse,
    DocumentSearchRequest,
    DocumentSearchResponse,
)
from app.rag.chunker import chunk_document
from app.rag.document_loader import (
    DocumentLoadError,
    UnsupportedDocumentTypeError,
    load_uploaded_document,
)
from app.rag.indexer import index_document_chunks
from app.rag.retriever import retrieve_document_chunks
from app.services.embedding_client import (
    EmbeddingClient,
    EmbeddingClientError,
    EmbeddingConfigurationError,
)
from app.services.document_index_queue import DocumentIndexQueue
from app.services.redis_client import RedisStore
from app.services.rerank_client import RerankClient
from app.workers.document_indexing import create_document_index_task

router = APIRouter(tags=["documents"])


@router.post("/documents/upload", response_model=DocumentIngestResponse)
async def upload_document(
    file: UploadFile = File(...),
    collection: str = Form("default"),
    redis_store: RedisStore = Depends(get_redis_store),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
) -> DocumentIngestResponse:
    raw_data = await file.read()

    try:
        document = load_uploaded_document(file.filename or "", raw_data)
        chunks = chunk_document(document)
        indexed_keys = await index_document_chunks(
            chunks,
            embedding_client=embedding_client,
            redis_store=redis_store,
            collection=collection,
        )
    except (DocumentLoadError, UnsupportedDocumentTypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmbeddingClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=502, detail=f"Redis indexing failed: {exc}") from exc

    return DocumentIngestResponse(
        document_id=document.document_id,
        file_name=document.metadata.file_name,
        file_type=document.metadata.file_type,
        collection=collection,
        chunk_count=len(chunks),
        indexed_keys=indexed_keys,
    )


@router.post(
    "/documents/upload/async",
    response_model=DocumentIndexTaskState,
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_document_async(
    file: UploadFile = File(...),
    redis_store: RedisStore = Depends(get_redis_store),
    document_index_queue: DocumentIndexQueue = Depends(get_document_index_queue),
) -> DocumentIndexTaskState:
    raw_data = await file.read()
    task = create_document_index_task(file.filename or "")
    try:
        await redis_store.save_index_task(task)
    except RedisError as exc:
        raise HTTPException(status_code=502, detail=f"Redis task creation failed: {exc}") from exc

    try:
        await document_index_queue.enqueue_document_index_task(
            task_id=task.task_id,
            file_name=task.file_name,
            raw_data=raw_data,
        )
    except Exception as exc:
        failed_task = task.model_copy(update={"status": "failed", "error_message": str(exc)})
        try:
            await redis_store.save_index_task(failed_task)
        except RedisError:
            pass
        raise HTTPException(status_code=502, detail=f"Document index enqueue failed: {exc}") from exc
    return task


@router.get("/documents/tasks/{task_id}", response_model=DocumentIndexTaskState)
async def get_document_index_task(
    task_id: str,
    redis_store: RedisStore = Depends(get_redis_store),
) -> DocumentIndexTaskState:
    try:
        task = await redis_store.get_index_task(task_id)
    except RedisError as exc:
        raise HTTPException(status_code=502, detail=f"Redis task lookup failed: {exc}") from exc
    if task is None:
        raise HTTPException(status_code=404, detail="Document index task not found.")
    return task


@router.post("/documents/search", response_model=DocumentSearchResponse)
async def search_documents(
    request: DocumentSearchRequest,
    redis_store: RedisStore = Depends(get_redis_store),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    rerank_client: RerankClient = Depends(get_rerank_client),
    llm_client: OpenAICompatibleClient = Depends(get_llm_client),
) -> DocumentSearchResponse:
    query_rewriter = build_query_rewriter(llm_client) if request.rewrite else None
    try:
        results = await retrieve_document_chunks(
            request.query,
            top_k=request.top_k,
            embedding_client=embedding_client,
            redis_store=redis_store,
            collection=request.collection,
            rerank_client=rerank_client,
            candidate_count=settings.rerank_candidate_count,
            query_rewriter=query_rewriter,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EmbeddingConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmbeddingClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=502, detail=f"Redis search failed: {exc}") from exc

    return DocumentSearchResponse(
        query=request.query,
        top_k=request.top_k,
        results=results,
    )
