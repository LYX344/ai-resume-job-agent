"""Smoke test: real reranker (SiliconFlow BAAI/bge-reranker-v2-m3).

1. Calls the rerank API directly to confirm it works and orders sensibly.
2. On the mixed index (resume + project_docs, no collection filter), compares
   resume-question hit_rate with vs without rerank, showing rerank's standalone
   value (better ordering, complementary to collection isolation).

Reuses the SiliconFlow key from EMBEDDING_API_KEY. Run with Redis up and the
resume + project docs already indexed (run smoke_resume_isolation.py first).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.dependencies import get_embedding_client
from app.core.config import settings
from app.evaluation.retrieval import find_keyword_hits, load_questions
from app.rag.retriever import retrieve_document_chunks
from app.services.redis_client import RedisStore
from app.services.rerank_client import OpenAICompatibleRerankClient


async def _hit_rate(*, rerank_client, candidate_count, embedding_client, redis_store) -> tuple[int, int]:
    questions = load_questions(PROJECT_ROOT / "data" / "eval" / "resume_questions.json")
    hits = 0
    for question in questions:
        results = await retrieve_document_chunks(
            question.question,
            top_k=3,
            embedding_client=embedding_client,
            redis_store=redis_store,
            rerank_client=rerank_client,
            candidate_count=candidate_count,
        )
        result_dicts = [{"content": r.content, "metadata": r.metadata} for r in results]
        if find_keyword_hits(question.expected_keywords, result_dicts):
            hits += 1
    return hits, len(questions)


async def main() -> int:
    redis_store = RedisStore.from_settings()
    embedding_client = get_embedding_client()
    rerank_client = OpenAICompatibleRerankClient(
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        model="BAAI/bge-reranker-v2-m3",
    )

    items = await rerank_client.rerank(
        "候选人的前端开发技能",
        [
            "熟悉 HTML、CSS、JavaScript，能实现浏览器插件页面和表单配置",
            "STM32F103 完成 OLED 菜单、DHT11、直流电机 PWM 调速",
            "Redis 向量检索、RAG 文档入库与切片",
        ],
        top_n=3,
    )
    print("rerank_order:", [(item.index, round(item.relevance_score, 4)) for item in items])

    no_rerank_hits, total = await _hit_rate(
        rerank_client=None,
        candidate_count=None,
        embedding_client=embedding_client,
        redis_store=redis_store,
    )
    rerank_hits, _ = await _hit_rate(
        rerank_client=rerank_client,
        candidate_count=20,
        embedding_client=embedding_client,
        redis_store=redis_store,
    )

    print("----- MIXED INDEX (no collection filter) -----")
    print(f"no_rerank: {no_rerank_hits}/{total} = {no_rerank_hits / total:.4f}")
    print(f"+rerank:   {rerank_hits}/{total} = {rerank_hits / total:.4f}")

    await redis_store.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
