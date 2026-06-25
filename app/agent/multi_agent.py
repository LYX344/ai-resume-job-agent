"""Multi-agent job-application workflows.

1. ``run_job_application_workflow``: a supervisor cyclic graph that orchestrates
   three specialist sub-agents (resume_analyst -> jd_matcher -> material_writer).
2. ``start_job_application_review`` / ``resume_job_application_review``: a
   human-in-the-loop (HITL) variant. The graph runs to a ``human_review``
   interrupt after the JD match, returns the match for human approval, then
   resumes from the checkpoint to generate the tailored material — demonstrating
   real checkpoint-based break/resume.
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, Field

from app.core.config import settings
from app.models.chat import ChatMessage
from app.rag.retriever import retrieve_document_chunks
from app.services.embedding_client import EmbeddingClient
from app.services.llm_client import OpenAICompatibleClient
from app.services.redis_client import RedisStore
from app.services.rerank_client import RerankClient


RESUME_COLLECTION = "resume"

_ANALYST_SYSTEM = (
    "你是简历分析专家。基于提供的简历内容，结构化提炼候选人的核心技能、代表项目经历"
    "和教育背景，用简洁要点输出。只能基于简历内容，不要编造简历中没有的信息。"
)
_MATCHER_SYSTEM = (
    "你是求职岗位匹配分析专家。对比岗位 JD 与候选人简历摘要，输出：1) 匹配亮点；"
    "2) 可能的能力缺口；3) 总体匹配度判断与投递建议。基于事实，不夸大。"
)
_WRITER_SYSTEM = (
    "你是求职材料撰写专家。基于岗位 JD、候选人简历摘要和匹配分析，撰写一段定制化的"
    "求职自我介绍（150-250 字），突出与岗位相关的亮点，语气专业真诚，不编造经历。"
)

# Module-level singleton checkpointer so HITL start + resume (two HTTP requests
# in the same process) share graph state. Production would use a shared
# Redis/Postgres checkpointer instead.
_REVIEW_CHECKPOINTER = InMemorySaver()


class JobApplicationStep(BaseModel):
    agent: str
    status: str
    detail: str = ""


class JobApplicationState(BaseModel):
    jd_text: str
    top_k: int = 5
    resume_summary: str = ""
    match_analysis: str = ""
    application_material: str = ""
    review_note: str = ""
    steps: list[JobApplicationStep] = Field(default_factory=list)


class JobApplicationReviewResult(BaseModel):
    status: str
    thread_id: str
    resume_summary: str = ""
    match_analysis: str = ""
    application_material: str = ""
    review_payload: dict[str, Any] | None = None
    steps: list[JobApplicationStep] = Field(default_factory=list)


async def _analyze_resume(
    state: JobApplicationState,
    *,
    llm_client: OpenAICompatibleClient,
    embedding_client: EmbeddingClient,
    redis_store: RedisStore,
    rerank_client: RerankClient | None,
) -> None:
    chunks = await retrieve_document_chunks(
        "候选人的核心技能、项目经历和教育背景",
        top_k=state.top_k,
        embedding_client=embedding_client,
        redis_store=redis_store,
        collection=RESUME_COLLECTION,
        rerank_client=rerank_client,
        candidate_count=settings.rerank_candidate_count,
    )
    context = "\n\n".join(chunk.content for chunk in chunks)
    if not context:
        state.resume_summary = "（未在简历库中检索到内容，请先上传简历到 resume 知识库。）"
        state.steps.append(JobApplicationStep(agent="resume_analyst", status="no_context"))
        return

    result = await llm_client.chat(
        messages=[
            ChatMessage(role="system", content=_ANALYST_SYSTEM),
            ChatMessage(role="user", content=f"简历内容：\n{context}"),
        ],
        temperature=0.2,
        max_tokens=600,
    )
    state.resume_summary = result.content
    state.steps.append(JobApplicationStep(agent="resume_analyst", status="done"))


async def _match_jd(state: JobApplicationState, *, llm_client: OpenAICompatibleClient) -> None:
    result = await llm_client.chat(
        messages=[
            ChatMessage(role="system", content=_MATCHER_SYSTEM),
            ChatMessage(
                role="user",
                content=f"岗位 JD：\n{state.jd_text}\n\n候选人简历摘要：\n{state.resume_summary}",
            ),
        ],
        temperature=0.2,
        max_tokens=600,
    )
    state.match_analysis = result.content
    state.steps.append(JobApplicationStep(agent="jd_matcher", status="done"))


async def _write_material(state: JobApplicationState, *, llm_client: OpenAICompatibleClient) -> None:
    note_line = (
        f"\n\n应聘者补充说明（请结合）：\n{state.review_note}" if state.review_note else ""
    )
    result = await llm_client.chat(
        messages=[
            ChatMessage(role="system", content=_WRITER_SYSTEM),
            ChatMessage(
                role="user",
                content=(
                    f"岗位 JD：\n{state.jd_text}\n\n简历摘要：\n{state.resume_summary}\n\n"
                    f"匹配分析：\n{state.match_analysis}{note_line}"
                ),
            ),
        ],
        temperature=0.3,
        max_tokens=700,
    )
    state.application_material = result.content
    state.steps.append(JobApplicationStep(agent="material_writer", status="done"))


async def run_job_application_workflow(
    jd_text: str,
    *,
    llm_client: OpenAICompatibleClient,
    embedding_client: EmbeddingClient,
    redis_store: RedisStore,
    rerank_client: RerankClient | None = None,
    top_k: int = 5,
) -> JobApplicationState:
    graph = _build_job_application_graph(
        llm_client=llm_client,
        embedding_client=embedding_client,
        redis_store=redis_store,
        rerank_client=rerank_client,
    )
    raw_result = await graph.ainvoke(JobApplicationState(jd_text=jd_text, top_k=top_k))
    return _coerce_state(raw_result)


def _build_job_application_graph(
    *,
    llm_client: OpenAICompatibleClient,
    embedding_client: EmbeddingClient,
    redis_store: RedisStore,
    rerank_client: RerankClient | None = None,
):
    builder = StateGraph(JobApplicationState)

    async def supervisor_node(raw_state: dict[str, Any] | JobApplicationState) -> dict[str, Any]:
        state = _coerce_state(raw_state)
        state.steps.append(
            JobApplicationStep(agent="supervisor", status="route", detail=_next_agent(state))
        )
        return {"steps": state.steps}

    async def resume_analyst_node(raw_state: dict[str, Any] | JobApplicationState) -> dict[str, Any]:
        state = _coerce_state(raw_state)
        await _analyze_resume(
            state,
            llm_client=llm_client,
            embedding_client=embedding_client,
            redis_store=redis_store,
            rerank_client=rerank_client,
        )
        return {"resume_summary": state.resume_summary, "steps": state.steps}

    async def jd_matcher_node(raw_state: dict[str, Any] | JobApplicationState) -> dict[str, Any]:
        state = _coerce_state(raw_state)
        await _match_jd(state, llm_client=llm_client)
        return {"match_analysis": state.match_analysis, "steps": state.steps}

    async def material_writer_node(
        raw_state: dict[str, Any] | JobApplicationState,
    ) -> dict[str, Any]:
        state = _coerce_state(raw_state)
        await _write_material(state, llm_client=llm_client)
        return {"application_material": state.application_material, "steps": state.steps}

    builder.add_node("supervisor", supervisor_node)
    builder.add_node("resume_analyst", resume_analyst_node)
    builder.add_node("jd_matcher", jd_matcher_node)
    builder.add_node("material_writer", material_writer_node)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        _supervisor_route,
        {
            "resume_analyst": "resume_analyst",
            "jd_matcher": "jd_matcher",
            "material_writer": "material_writer",
            END: END,
        },
    )
    builder.add_edge("resume_analyst", "supervisor")
    builder.add_edge("jd_matcher", "supervisor")
    builder.add_edge("material_writer", "supervisor")
    return builder.compile()


async def start_job_application_review(
    jd_text: str,
    *,
    thread_id: str,
    llm_client: OpenAICompatibleClient,
    embedding_client: EmbeddingClient,
    redis_store: RedisStore,
    rerank_client: RerankClient | None = None,
    top_k: int = 5,
) -> JobApplicationReviewResult:
    graph = _build_review_graph(
        llm_client=llm_client,
        embedding_client=embedding_client,
        redis_store=redis_store,
        rerank_client=rerank_client,
    )
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke(JobApplicationState(jd_text=jd_text, top_k=top_k), config=config)
    return await _review_result(graph, config, thread_id)


async def resume_job_application_review(
    thread_id: str,
    decision: dict[str, Any],
    *,
    llm_client: OpenAICompatibleClient,
    embedding_client: EmbeddingClient,
    redis_store: RedisStore,
    rerank_client: RerankClient | None = None,
) -> JobApplicationReviewResult:
    graph = _build_review_graph(
        llm_client=llm_client,
        embedding_client=embedding_client,
        redis_store=redis_store,
        rerank_client=rerank_client,
    )
    config = {"configurable": {"thread_id": thread_id}}
    await graph.ainvoke(Command(resume=decision), config=config)
    return await _review_result(graph, config, thread_id)


def _build_review_graph(
    *,
    llm_client: OpenAICompatibleClient,
    embedding_client: EmbeddingClient,
    redis_store: RedisStore,
    rerank_client: RerankClient | None = None,
):
    builder = StateGraph(JobApplicationState)

    async def resume_analyst_node(raw_state: dict[str, Any] | JobApplicationState) -> dict[str, Any]:
        state = _coerce_state(raw_state)
        await _analyze_resume(
            state,
            llm_client=llm_client,
            embedding_client=embedding_client,
            redis_store=redis_store,
            rerank_client=rerank_client,
        )
        return {"resume_summary": state.resume_summary, "steps": state.steps}

    async def jd_matcher_node(raw_state: dict[str, Any] | JobApplicationState) -> dict[str, Any]:
        state = _coerce_state(raw_state)
        await _match_jd(state, llm_client=llm_client)
        return {"match_analysis": state.match_analysis, "steps": state.steps}

    async def human_review_node(raw_state: dict[str, Any] | JobApplicationState) -> dict[str, Any]:
        state = _coerce_state(raw_state)
        decision = interrupt(
            {
                "message": "请审核匹配分析，确认是否生成投递材料，可补充说明。",
                "match_analysis": state.match_analysis,
            }
        )
        note = decision.get("note", "") if isinstance(decision, dict) else str(decision)
        state.review_note = note
        state.steps.append(JobApplicationStep(agent="human_review", status="resumed", detail=note))
        return {"review_note": note, "steps": state.steps}

    async def material_writer_node(
        raw_state: dict[str, Any] | JobApplicationState,
    ) -> dict[str, Any]:
        state = _coerce_state(raw_state)
        await _write_material(state, llm_client=llm_client)
        return {"application_material": state.application_material, "steps": state.steps}

    builder.add_node("resume_analyst", resume_analyst_node)
    builder.add_node("jd_matcher", jd_matcher_node)
    builder.add_node("human_review", human_review_node)
    builder.add_node("material_writer", material_writer_node)

    builder.add_edge(START, "resume_analyst")
    builder.add_edge("resume_analyst", "jd_matcher")
    builder.add_edge("jd_matcher", "human_review")
    builder.add_edge("human_review", "material_writer")
    builder.add_edge("material_writer", END)
    return builder.compile(checkpointer=_REVIEW_CHECKPOINTER)


async def _review_result(graph, config, thread_id: str) -> JobApplicationReviewResult:
    snapshot = await graph.aget_state(config)
    state = _coerce_state(snapshot.values)
    interrupted = bool(snapshot.next)
    review_payload: dict[str, Any] | None = None
    if interrupted:
        for task in snapshot.tasks:
            for pending in getattr(task, "interrupts", ()) or ():
                value = getattr(pending, "value", None)
                review_payload = value if isinstance(value, dict) else {"value": value}
        status = "interrupted"
    else:
        status = "completed"
    return JobApplicationReviewResult(
        status=status,
        thread_id=thread_id,
        resume_summary=state.resume_summary,
        match_analysis=state.match_analysis,
        application_material=state.application_material,
        review_payload=review_payload,
        steps=state.steps,
    )


def _next_agent(state: JobApplicationState) -> str:
    completed = {
        step.agent for step in state.steps if step.status in {"done", "no_context"}
    }
    if "resume_analyst" not in completed:
        return "resume_analyst"
    if "jd_matcher" not in completed:
        return "jd_matcher"
    if "material_writer" not in completed:
        return "material_writer"
    return "FINISH"


def _supervisor_route(raw_state: dict[str, Any] | JobApplicationState) -> str:
    state = _coerce_state(raw_state)
    next_agent = _next_agent(state)
    if next_agent == "FINISH":
        return END
    return next_agent


def _coerce_state(raw_state: dict[str, Any] | JobApplicationState) -> JobApplicationState:
    if isinstance(raw_state, JobApplicationState):
        return raw_state
    return JobApplicationState.model_validate(raw_state)
