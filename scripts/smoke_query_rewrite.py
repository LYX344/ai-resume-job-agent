"""Smoke test: query rewriting on colloquial / elliptical resume questions.

Shows the rewrite (pronoun resolution + completion) and compares resume-library
retrieval hit_rate with vs without rewrite on deliberately vague questions.
Run with Redis up, resume indexed, and the LLM reachable.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.dependencies import get_embedding_client
from app.evaluation.retrieval import find_keyword_hits
from app.rag.query_rewriter import LLMQueryRewriter
from app.rag.retriever import retrieve_document_chunks
from app.services.llm_client import OpenAICompatibleClient
from app.services.redis_client import RedisStore
from app.services.rerank_client import build_rerank_client_from_settings


COLLOQUIAL = [
    {"q": "他会前端那些啥", "kw": ["HTML", "CSS", "JavaScript"]},
    {"q": "那个浏览器插件项目用啥技术做的", "kw": ["JavaScript", "OpenAI"]},
    {"q": "啥时候能到岗", "kw": ["2026", "暑期"]},
    {"q": "读的啥学校啥专业", "kw": ["示例大学", "计算机科学与技术"]},
    {"q": "那个聊天机器人用啥写的", "kw": ["Python", "discord.py"]},
]


async def main() -> int:
    llm_client = OpenAICompatibleClient.from_settings()
    redis_store = RedisStore.from_settings()
    embedding_client = get_embedding_client()
    rerank_client = build_rerank_client_from_settings()
    rewriter = LLMQueryRewriter(llm_client)

    lines: list[str] = ["== query rewrite 示例 =="]
    for item in COLLOQUIAL:
        rewritten = await rewriter.rewrite(item["q"])
        lines.append(f"原: {item['q']}  ->  改写: {rewritten}")
    out_path = PROJECT_ROOT / "data" / "uploads" / "query_rewrite_smoke.txt"
    out_path.write_text("\n".join(lines), encoding="utf-8")

    async def hit_rate(use_rewrite: bool) -> tuple[int, int]:
        hits = 0
        for item in COLLOQUIAL:
            results = await retrieve_document_chunks(
                item["q"],
                top_k=3,
                embedding_client=embedding_client,
                redis_store=redis_store,
                collection="resume",
                rerank_client=rerank_client,
                candidate_count=20,
                query_rewriter=rewriter if use_rewrite else None,
            )
            result_dicts = [{"content": r.content, "metadata": r.metadata} for r in results]
            if find_keyword_hits(item["kw"], result_dicts):
                hits += 1
        return hits, len(COLLOQUIAL)

    no_rewrite_hits, total = await hit_rate(False)
    rewrite_hits, _ = await hit_rate(True)

    print("----- COLLOQUIAL RESUME QUESTIONS -----")
    print(f"no_rewrite: {no_rewrite_hits}/{total} = {no_rewrite_hits / total:.4f}")
    print(f"+rewrite:   {rewrite_hits}/{total} = {rewrite_hits / total:.4f}")
    print(f"rewrite_examples_utf8: {out_path}")

    await llm_client.aclose()
    await redis_store.aclose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
