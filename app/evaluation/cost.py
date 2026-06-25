"""RAG/LLM 成本估算。

从 answer eval 报告（含真实 usage 或估算 token）汇总调用次数、token、latency 和重试，
并按可配置单价估算成本。本地反代通常免费，单价默认为 0；如需估算云端成本，
可传入每 1K token 的 prompt/completion 价格。
"""

from __future__ import annotations

from typing import Any

DEFAULT_PROMPT_PRICE_PER_1K = 0.0
DEFAULT_COMPLETION_PRICE_PER_1K = 0.0


def estimate_cost(
    *,
    prompt_tokens: int,
    completion_tokens: int,
    prompt_price_per_1k: float,
    completion_price_per_1k: float,
) -> dict[str, Any]:
    prompt_cost = prompt_tokens / 1000 * prompt_price_per_1k
    completion_cost = completion_tokens / 1000 * completion_price_per_1k
    return {
        "prompt_cost": round(prompt_cost, 6),
        "completion_cost": round(completion_cost, 6),
        "total_cost": round(prompt_cost + completion_cost, 6),
    }


def record_tokens(record: dict[str, Any]) -> tuple[int, int, int]:
    """返回单条记录的 (prompt_tokens, completion_tokens, reasoning_tokens)。

    优先使用真实 usage，缺失时回退到评测脚本的估算 token。
    """
    usage = record.get("usage")
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        reasoning = 0
        details = usage.get("completion_tokens_details")
        if isinstance(details, dict):
            reasoning = int(details.get("reasoning_tokens") or 0)
        if prompt or completion:
            return prompt, completion, reasoning
    prompt = int(record.get("estimated_prompt_tokens") or 0)
    completion = int(record.get("estimated_answer_tokens") or 0)
    return prompt, completion, 0


def build_cost_report(
    eval_report: dict[str, Any],
    *,
    prompt_price_per_1k: float = DEFAULT_PROMPT_PRICE_PER_1K,
    completion_price_per_1k: float = DEFAULT_COMPLETION_PRICE_PER_1K,
) -> dict[str, Any]:
    records = eval_report.get("records", [])
    summary = eval_report.get("summary", {})

    total_questions = len(records)
    total_calls = sum(int(record.get("attempts") or 1) for record in records)
    retry_calls = max(0, total_calls - total_questions)
    success_calls = len(
        [record for record in records if record.get("status_code") == 200]
    )

    total_prompt = 0
    total_completion = 0
    total_reasoning = 0
    uses_real_usage = False
    for record in records:
        prompt, completion, reasoning = record_tokens(record)
        total_prompt += prompt
        total_completion += completion
        total_reasoning += reasoning
        if isinstance(record.get("usage"), dict):
            uses_real_usage = True

    cost = estimate_cost(
        prompt_tokens=total_prompt,
        completion_tokens=total_completion,
        prompt_price_per_1k=prompt_price_per_1k,
        completion_price_per_1k=completion_price_per_1k,
    )

    avg_cost_per_question = (
        round(cost["total_cost"] / total_questions, 6) if total_questions else 0.0
    )
    avg_cost_per_call = (
        round(cost["total_cost"] / total_calls, 6) if total_calls else 0.0
    )
    retry_cost = round(avg_cost_per_call * retry_calls, 6)

    return {
        "token_source": "real_usage" if uses_real_usage else "estimated",
        "total_questions": total_questions,
        "total_calls": total_calls,
        "retry_calls": retry_calls,
        "success_calls": success_calls,
        "avg_latency_ms": summary.get("avg_latency_ms"),
        "prompt_price_per_1k": prompt_price_per_1k,
        "completion_price_per_1k": completion_price_per_1k,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "total_reasoning_tokens": total_reasoning,
        "total_tokens": total_prompt + total_completion,
        "prompt_cost": cost["prompt_cost"],
        "completion_cost": cost["completion_cost"],
        "total_cost": cost["total_cost"],
        "avg_cost_per_question": avg_cost_per_question,
        "avg_cost_per_call": avg_cost_per_call,
        "retry_cost": retry_cost,
    }


COST_OPTIMIZATION_NOTES = [
    "开发期用 fake embedding 和 mock 测试，避免真实 API 调用产生 token 成本。",
    "运行期无检索 sources 时直接拒答，不调用 LLM，避免无意义的生成 token。",
    "用 top_k 限制检索片段数量、max_tokens 限制生成长度，控制单次 prompt/completion token。",
    "RAG 先做 retrieval eval 再做 answer eval，避免在检索不可靠时盲目消耗 LLM token。",
    "失败分类区分可重试/不可重试，避免对永久性错误做无意义重试而浪费 token。",
    "推理模型（如 deepseek）reasoning 占大量 token，需结合场景权衡是否启用思考。",
]
