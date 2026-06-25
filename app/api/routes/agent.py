import time
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query
from redis import RedisError

from app.agent.multi_agent import (
    resume_job_application_review,
    run_job_application_workflow,
    start_job_application_review,
)
from app.agent.workflow import (
    get_agent_checkpoint_snapshot,
    list_agent_checkpoint_snapshots,
    run_agent_workflow,
)
from app.api.dependencies import (
    get_embedding_client,
    get_llm_client,
    get_mcp_client,
    get_mysql_store,
    get_redis_store,
    get_rerank_client,
    get_trace_store,
)
from app.core.config import settings
from app.models.agent import (
    AgentCheckpointHistoryResponse,
    AgentCheckpointSnapshotResponse,
    AgentRunRequest,
    AgentRunResponse,
    AgentStep,
    JobApplicationRequest,
    JobApplicationResponse,
    JobApplicationResumeRequest,
    JobApplicationReviewRequest,
    JobApplicationReviewResponse,
    JobApplicationStepInfo,
)
from app.services.embedding_client import (
    EmbeddingClient,
    EmbeddingClientError,
    EmbeddingConfigurationError,
)
from app.services.llm_client import LLMClientError, LLMConfigurationError, OpenAICompatibleClient
from app.services.mcp_client import MCPClient
from app.services.mysql_client import MySQLClientError, MySQLStore, SQLSafetyError
from app.models.trace import TraceRecord, TraceStep
from app.services.redis_client import RedisStore
from app.services.rerank_client import RerankClient
from app.services.trace_store import TraceStore

router = APIRouter(tags=["agent"])


def _extract_trace_tool_calls(steps: list[AgentStep]) -> list[dict]:
    """Summarize built-in and MCP tool calls from agent steps for tracing."""
    tool_calls: list[dict] = []
    for step in steps:
        data = step.data or {}
        if step.name == "call_tools" and data.get("tool"):
            tool_calls.append(
                {"name": data["tool"], "status": step.status, "kind": "builtin"}
            )
        for executed in data.get("executed_tool_calls") or []:
            name = str(executed.get("name", ""))
            tool_calls.append(
                {
                    "name": name,
                    "status": executed.get("status", ""),
                    "kind": "mcp" if name.startswith("mcp_") else "llm_tool",
                }
            )
    return tool_calls


@router.post("/agent/job-application", response_model=JobApplicationResponse)
async def run_job_application(
    request: JobApplicationRequest,
    redis_store: RedisStore = Depends(get_redis_store),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    llm_client: OpenAICompatibleClient = Depends(get_llm_client),
    rerank_client: RerankClient = Depends(get_rerank_client),
) -> JobApplicationResponse:
    try:
        state = await run_job_application_workflow(
            request.jd_text,
            llm_client=llm_client,
            embedding_client=embedding_client,
            redis_store=redis_store,
            rerank_client=rerank_client,
            top_k=request.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (EmbeddingConfigurationError, LLMConfigurationError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (EmbeddingClientError, LLMClientError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=502, detail=f"Redis error: {exc}") from exc

    return JobApplicationResponse(
        resume_summary=state.resume_summary,
        match_analysis=state.match_analysis,
        application_material=state.application_material,
        steps=[
            JobApplicationStepInfo(agent=step.agent, status=step.status, detail=step.detail)
            for step in state.steps
        ],
    )


@router.post("/agent/job-application/review", response_model=JobApplicationReviewResponse)
async def start_job_application_review_endpoint(
    request: JobApplicationReviewRequest,
    redis_store: RedisStore = Depends(get_redis_store),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    llm_client: OpenAICompatibleClient = Depends(get_llm_client),
    rerank_client: RerankClient = Depends(get_rerank_client),
) -> JobApplicationReviewResponse:
    thread_id = uuid4().hex
    try:
        result = await start_job_application_review(
            request.jd_text,
            thread_id=thread_id,
            llm_client=llm_client,
            embedding_client=embedding_client,
            redis_store=redis_store,
            rerank_client=rerank_client,
            top_k=request.top_k,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (EmbeddingConfigurationError, LLMConfigurationError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (EmbeddingClientError, LLMClientError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=502, detail=f"Redis error: {exc}") from exc
    return _to_review_response(result)


@router.post("/agent/job-application/resume", response_model=JobApplicationReviewResponse)
async def resume_job_application_review_endpoint(
    request: JobApplicationResumeRequest,
    redis_store: RedisStore = Depends(get_redis_store),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    llm_client: OpenAICompatibleClient = Depends(get_llm_client),
    rerank_client: RerankClient = Depends(get_rerank_client),
) -> JobApplicationReviewResponse:
    try:
        result = await resume_job_application_review(
            request.thread_id,
            {"note": request.note, "approved": request.approved},
            llm_client=llm_client,
            embedding_client=embedding_client,
            redis_store=redis_store,
            rerank_client=rerank_client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (EmbeddingConfigurationError, LLMConfigurationError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (EmbeddingClientError, LLMClientError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=502, detail=f"Redis error: {exc}") from exc
    return _to_review_response(result)


def _to_review_response(result) -> JobApplicationReviewResponse:
    return JobApplicationReviewResponse(
        status=result.status,
        thread_id=result.thread_id,
        resume_summary=result.resume_summary,
        match_analysis=result.match_analysis,
        application_material=result.application_material,
        review_payload=result.review_payload,
        steps=[
            JobApplicationStepInfo(agent=step.agent, status=step.status, detail=step.detail)
            for step in result.steps
        ],
    )


@router.get(
    "/agent/checkpoints/{thread_id}/history",
    response_model=AgentCheckpointHistoryResponse,
)
async def list_agent_checkpoints(
    thread_id: str,
    limit: int = Query(default=20, ge=1, le=100),
) -> AgentCheckpointHistoryResponse:
    history = list_agent_checkpoint_snapshots(thread_id, limit=limit)
    if history is None:
        raise HTTPException(status_code=404, detail="Agent checkpoint thread not found.")
    return history


@router.get(
    "/agent/checkpoints/{thread_id}",
    response_model=AgentCheckpointSnapshotResponse,
)
async def get_agent_checkpoint(thread_id: str) -> AgentCheckpointSnapshotResponse:
    snapshot = get_agent_checkpoint_snapshot(thread_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Agent checkpoint thread not found.")
    return snapshot


@router.post("/agent/run", response_model=AgentRunResponse)
async def run_agent(
    request: AgentRunRequest,
    redis_store: RedisStore = Depends(get_redis_store),
    mysql_store: MySQLStore = Depends(get_mysql_store),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    llm_client: OpenAICompatibleClient = Depends(get_llm_client),
    mcp_client: MCPClient = Depends(get_mcp_client),
    trace_store: TraceStore = Depends(get_trace_store),
) -> AgentRunResponse:
    started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat()
    try:
        response = await run_agent_workflow(
            request,
            redis_store=redis_store,
            mysql_store=mysql_store,
            embedding_client=embedding_client,
            llm_client=llm_client,
            mcp_client=mcp_client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RedisError as exc:
        raise HTTPException(status_code=502, detail=f"Redis operation failed: {exc}") from exc
    except EmbeddingConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EmbeddingClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except LLMConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except SQLSafetyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except MySQLClientError as exc:
        raise HTTPException(status_code=502, detail=f"MySQL operation failed: {exc}") from exc

    if settings.trace_enabled:
        try:
            trace_store.append(
                TraceRecord(
                    trace_id=uuid4().hex,
                    kind="agent",
                    query=request.query,
                    intent=response.intent,
                    started_at=started_at,
                    duration_ms=round((time.perf_counter() - started) * 1000, 2),
                    step_count=len(response.steps),
                    steps=[
                        TraceStep(name=step.name, status=step.status, detail=step.detail)
                        for step in response.steps
                    ],
                    usage=response.usage,
                    model=response.model,
                    tool_calls=_extract_trace_tool_calls(response.steps),
                )
            )
        except OSError:
            pass
    return response
