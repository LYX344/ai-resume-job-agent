"""Smoke test: real multi-agent job-application workflow.

Runs supervisor -> resume_analyst -> jd_matcher -> material_writer against the
real resume knowledge base and the configured LLM. Writes the full output to a
UTF-8 file for inspection.

Run with Redis up, resume indexed (smoke_resume_isolation.py) and LLM reachable.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.multi_agent import run_job_application_workflow
from app.api.dependencies import get_embedding_client
from app.services.llm_client import OpenAICompatibleClient
from app.services.redis_client import RedisStore
from app.services.rerank_client import build_rerank_client_from_settings


async def main() -> int:
    llm_client = OpenAICompatibleClient.from_settings()
    redis_store = RedisStore.from_settings()
    embedding_client = get_embedding_client()
    rerank_client = build_rerank_client_from_settings()

    jd_text = (
        "招聘 AI 应用开发实习生：要求熟悉 Python、LangChain/LangGraph、RAG 与向量检索，"
        "了解 FastAPI 和 Redis，有 Agent 或知识库项目经验者优先。"
    )

    state = await run_job_application_workflow(
        jd_text,
        llm_client=llm_client,
        embedding_client=embedding_client,
        redis_store=redis_store,
        rerank_client=rerank_client,
        top_k=5,
    )

    sections = [
        "=== resume_summary ===\n" + state.resume_summary,
        "=== match_analysis ===\n" + state.match_analysis,
        "=== application_material ===\n" + state.application_material,
        "=== steps ===\n" + " -> ".join(f"{s.agent}:{s.status}" for s in state.steps),
    ]
    output_path = PROJECT_ROOT / "data" / "uploads" / "job_application_smoke.txt"
    output_path.write_text("\n\n".join(sections), encoding="utf-8")

    print("agents:", [step.agent for step in state.steps])
    print("resume_summary_len:", len(state.resume_summary))
    print("match_analysis_len:", len(state.match_analysis))
    print("application_material_len:", len(state.application_material))
    print("written_utf8:", output_path)

    await llm_client.aclose()
    await redis_store.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
