"""Query rewriting for RAG retrieval.

User questions are often colloquial, elliptical or full of pronouns ("它怎么做
的"). Rewriting the query before embedding/retrieval improves recall by
resolving references, completing omissions and keeping key entities/terms. This
is the retrieval-side complement to rerank (rewrite optimizes "ask the right
thing", rerank optimizes "rank the right thing").

Providers:
- ``LLMQueryRewriter``: uses the LLM to rewrite; degrades to the original query
  on any LLM error so retrieval never breaks.
- ``IdentityQueryRewriter``: returns the query unchanged (disabled / no key).
"""

from __future__ import annotations

from typing import Protocol

from app.core.config import settings
from app.models.chat import ChatMessage
from app.services.llm_client import LLMClientError, OpenAICompatibleClient


_REWRITE_SYSTEM = (
    "你是检索查询改写器。把用户问题改写成更适合向量检索的简洁查询："
    "消解指代、补全省略、保留关键实体和术语。只输出改写后的查询本身，"
    "不要解释、不要加引号、不要分点。"
)


class QueryRewriter(Protocol):
    async def rewrite(self, query: str) -> str: ...


class IdentityQueryRewriter:
    name = "identity"

    async def rewrite(self, query: str) -> str:
        return query


class LLMQueryRewriter:
    name = "llm"

    def __init__(self, llm_client: OpenAICompatibleClient, *, max_tokens: int = 120) -> None:
        self._llm = llm_client
        self._max_tokens = max_tokens

    async def rewrite(self, query: str) -> str:
        if not query.strip():
            return query
        try:
            result = await self._llm.chat(
                messages=[
                    ChatMessage(role="system", content=_REWRITE_SYSTEM),
                    ChatMessage(role="user", content=query),
                ],
                temperature=0.0,
                max_tokens=self._max_tokens,
            )
        except LLMClientError:
            return query
        rewritten = (result.content or "").strip()
        if not rewritten:
            return query
        # 推理模型偶发把思考过程写进 content（reasoning fallback 的副作用）；正常改写应
        # 简短，过长则视为异常输出，降级用原 query，避免把思考过程当查询。
        if len(rewritten) > max(60, len(query) * 4):
            return query
        return rewritten


def build_query_rewriter(
    llm_client: OpenAICompatibleClient,
    *,
    provider: str | None = None,
) -> QueryRewriter:
    resolved = (provider or settings.query_rewrite_provider or "identity").lower()
    if resolved == "llm":
        return LLMQueryRewriter(llm_client, max_tokens=settings.query_rewrite_max_tokens)
    return IdentityQueryRewriter()
