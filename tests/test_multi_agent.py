from types import SimpleNamespace

import pytest

from app.agent.multi_agent import (
    resume_job_application_review,
    run_job_application_workflow,
    start_job_application_review,
)
from app.models.document import DocumentSearchResult
from app.models.embedding import TextEmbedding


class FakeLLM:
    def __init__(self) -> None:
        self.calls: list[list] = []

    async def chat(self, *, messages, model=None, temperature=None, max_tokens=None):
        self.calls.append(messages)
        system = messages[0].content
        if "简历分析" in system:
            content = "核心技能：FastAPI、Redis、LangGraph；项目：浏览器翻译插件"
        elif "匹配" in system:
            content = "匹配亮点：RAG/LangGraph 对口；缺口：生产经验有限；建议：可投递"
        else:
            content = "我是一名熟悉 RAG 与 LangGraph 的候选人，期待加入贵司实习。"
        return SimpleNamespace(content=content, model="fake", finish_reason="stop", usage=None)


class FakeEmbedding:
    async def embed_text(self, text: str) -> TextEmbedding:
        return TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4])

    async def embed_texts(self, texts: list[str]) -> list[TextEmbedding]:
        return [TextEmbedding(text=text, embedding=[0.1, 0.2, 0.3, 0.4]) for text in texts]


class FakeRedis:
    def __init__(self, chunks: list[DocumentSearchResult] | None = None) -> None:
        self._chunks = chunks if chunks is not None else [
            DocumentSearchResult(
                key="doc:resume:0",
                content="熟悉 FastAPI、Redis、LangGraph，做过浏览器翻译插件和 Discord Bot",
                metadata={"collection": "resume"},
                distance=0.1,
            )
        ]

    async def ensure_vector_index(self, index_config=None) -> None:
        return None

    async def search_document_chunks(
        self, query_embedding, *, top_k=5, collection=None, index_config=None
    ) -> list[DocumentSearchResult]:
        assert collection == "resume"
        return self._chunks[:top_k]


@pytest.mark.anyio
async def test_job_application_supervisor_runs_three_agents() -> None:
    llm = FakeLLM()

    state = await run_job_application_workflow(
        "招聘 AI 应用开发实习生，要求熟悉 RAG 和 LangGraph",
        llm_client=llm,
        embedding_client=FakeEmbedding(),
        redis_store=FakeRedis(),
        rerank_client=None,
        top_k=3,
    )

    assert state.resume_summary
    assert state.match_analysis
    assert state.application_material
    assert len(llm.calls) == 3

    agents = [step.agent for step in state.steps]
    assert "resume_analyst" in agents
    assert "jd_matcher" in agents
    assert "material_writer" in agents
    assert agents.count("supervisor") >= 3


@pytest.mark.anyio
async def test_job_application_handles_empty_resume() -> None:
    llm = FakeLLM()

    state = await run_job_application_workflow(
        "招聘 AI 应用开发实习生",
        llm_client=llm,
        embedding_client=FakeEmbedding(),
        redis_store=FakeRedis(chunks=[]),
        rerank_client=None,
        top_k=3,
    )

    assert "未在简历库" in state.resume_summary
    assert len(llm.calls) == 2
    statuses = {step.agent: step.status for step in state.steps}
    assert statuses["resume_analyst"] == "no_context"


@pytest.mark.anyio
async def test_job_application_review_interrupts_then_resumes() -> None:
    llm = FakeLLM()
    deps = {
        "llm_client": llm,
        "embedding_client": FakeEmbedding(),
        "redis_store": FakeRedis(),
        "rerank_client": None,
    }

    started = await start_job_application_review(
        "招聘 RAG 实习生", thread_id="review-test-1", top_k=3, **deps
    )

    assert started.status == "interrupted"
    assert started.resume_summary
    assert started.match_analysis
    assert not started.application_material
    assert started.review_payload is not None
    assert "match_analysis" in started.review_payload
    assert len(llm.calls) == 2

    resumed = await resume_job_application_review(
        "review-test-1", {"note": "我也接触过 FastAPI 和 Redis"}, **deps
    )

    assert resumed.status == "completed"
    assert resumed.application_material
    assert len(llm.calls) == 3
    agents = [step.agent for step in resumed.steps]
    assert "human_review" in agents
