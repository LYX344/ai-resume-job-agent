import json
import re
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.evaluation.retrieval import (
    DEFAULT_API_BASE_URL,
    EvalQuestion,
    estimate_token_count,
    find_keyword_hits,
    load_questions,
    normalize_api_base,
)


NO_CONTEXT_MARKERS = [
    "没有在知识库",
    "无法基于",
    "不知道",
    "上下文不足",
    "未检索到",
]
TRANSIENT_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
CONFIGURATION_ERROR_MARKERS = [
    "api_key is not configured",
    "llm_api_key is not configured",
    "embedding_api_key is not configured",
    "is not configured",
]


def find_text_keyword_hits(expected_keywords: list[str], text: str) -> list[str]:
    haystack = text.lower()
    return [keyword for keyword in expected_keywords if keyword.lower() in haystack]


def extract_citation_ids(answer: str) -> list[int]:
    return sorted({int(match) for match in re.findall(r"\[(\d+)\]", answer)})


def detect_refusal(answer: str) -> bool:
    normalized = answer.strip().lower()
    return any(marker.lower() in normalized for marker in NO_CONTEXT_MARKERS)


def classify_error_category(status_code: int, error: str | None = None) -> str | None:
    if status_code == 200:
        return None

    normalized_error = (error or "").lower()
    if any(marker in normalized_error for marker in CONFIGURATION_ERROR_MARKERS):
        return "configuration_error"
    if status_code == 0:
        return "request_error"
    if status_code in {400, 422}:
        return "request_validation_error"
    if status_code in {401, 403}:
        return "authentication_or_permission_error"
    if status_code == 404:
        return "endpoint_not_found"
    if status_code == 408:
        return "timeout"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "provider_transient_error"
    return "http_error"


def should_retry_error(status_code: int, error: str | None = None) -> bool:
    if classify_error_category(status_code, error) == "configuration_error":
        return False
    return status_code == 0 or status_code in TRANSIENT_HTTP_STATUS_CODES


def compact_source(source: dict[str, Any], rank: int) -> dict[str, Any]:
    metadata = source.get("metadata", {})
    source_name = "unknown"
    if isinstance(metadata, dict):
        source_name = str(metadata.get("source") or metadata.get("file_name") or "unknown")

    content = str(source.get("content", ""))
    return {
        "rank": rank,
        "source_id": source.get("source_id", rank),
        "key": str(source.get("key", "")),
        "source": source_name,
        "distance": source.get("distance"),
        "content_preview": content[:240],
    }


def score_answer(
    *,
    question: EvalQuestion,
    answer: str,
    sources: list[dict[str, Any]],
    status_code: int,
    latency_ms: float,
    top_k: int,
    model: str | None = None,
    finish_reason: str | None = None,
    usage: dict[str, Any] | None = None,
    error: str | None = None,
    attempts: int = 1,
) -> dict[str, Any]:
    source_keyword_hits = find_keyword_hits(question.expected_keywords, sources)
    answer_keyword_hits = find_text_keyword_hits(question.expected_keywords, answer)
    citation_ids = extract_citation_ids(answer)
    valid_citation_ids = [
        citation_id for citation_id in citation_ids if 1 <= citation_id <= len(sources)
    ]
    invalid_citation_ids = [
        citation_id for citation_id in citation_ids if citation_id not in valid_citation_ids
    ]
    source_hit = bool(source_keyword_hits)
    answer_keyword_hit = bool(answer_keyword_hits) or not question.expected_keywords
    citation_match = bool(citation_ids) and not invalid_citation_ids
    refused = detect_refusal(answer)
    answer_passed = (
        status_code == 200
        and bool(sources)
        and source_hit
        and answer_keyword_hit
        and citation_match
        and not refused
    )
    source_text = "\n".join(str(source.get("content", "")) for source in sources)
    answer_keyword_coverage = (
        round(len(answer_keyword_hits) / len(question.expected_keywords), 4)
        if question.expected_keywords
        else 1.0
    )

    failure_reasons = build_failure_reasons(
        status_code=status_code,
        source_count=len(sources),
        source_hit=source_hit,
        answer_keyword_hit=answer_keyword_hit,
        citation_match=citation_match,
        refused=refused,
        error=error,
    )
    record: dict[str, Any] = {
        "id": question.id,
        "question": question.question,
        "expected_keywords": question.expected_keywords,
        "notes": question.notes,
        "top_k": top_k,
        "status_code": status_code,
        "latency_ms": latency_ms,
        "attempts": attempts,
        "answer": answer,
        "answer_preview": answer[:240],
        "model": model,
        "finish_reason": finish_reason,
        "usage": usage,
        "sources": [compact_source(source, index + 1) for index, source in enumerate(sources)],
        "source_count": len(sources),
        "source_keyword_hits": source_keyword_hits,
        "source_hit": source_hit,
        "answer_keyword_hits": answer_keyword_hits,
        "answer_keyword_hit": answer_keyword_hit,
        "answer_keyword_coverage": answer_keyword_coverage,
        "citation_ids": citation_ids,
        "valid_citation_ids": valid_citation_ids,
        "invalid_citation_ids": invalid_citation_ids,
        "citation_match": citation_match,
        "refused": refused,
        "failure_reasons": failure_reasons,
        "primary_failure_reason": failure_reasons[0] if failure_reasons else None,
        "error_category": classify_error_category(status_code, error),
        "retryable": should_retry_error(status_code, error),
        "answer_passed": answer_passed,
        "estimated_prompt_tokens": estimate_token_count(f"{question.question}\n{source_text}"),
        "estimated_answer_tokens": estimate_token_count(answer),
    }
    if error is not None:
        record["error"] = error
    return record


def build_failure_reasons(
    *,
    status_code: int,
    source_count: int,
    source_hit: bool,
    answer_keyword_hit: bool,
    citation_match: bool,
    refused: bool,
    error: str | None = None,
) -> list[str]:
    reasons: list[str] = []
    error_category = classify_error_category(status_code, error)
    if error_category is not None:
        reasons.append(error_category)
    if source_count == 0:
        reasons.append("no_sources")
    if not source_hit:
        reasons.append("source_keywords_missing")
    if not answer_keyword_hit:
        reasons.append("answer_keywords_missing")
    if not citation_match:
        reasons.append("citation_mismatch")
    if refused:
        reasons.append("refused")
    return reasons


def evaluate_answer_questions(
    *,
    questions: list[EvalQuestion],
    api_base: str = DEFAULT_API_BASE_URL,
    top_k: int = 3,
    timeout_seconds: float = 30.0,
    model: str | None = None,
    temperature: float | None = 0.0,
    max_tokens: int | None = None,
    max_retries: int = 1,
    retry_delay_seconds: float = 0.5,
    retry_backoff_multiplier: float = 1.5,
    inter_request_delay_seconds: float = 0.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    api_base = normalize_api_base(api_base)
    own_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds)

    records: list[dict[str, Any]] = []
    try:
        for question_index, question in enumerate(questions):
            payload: dict[str, Any] = {
                "query": question.question,
                "top_k": top_k,
                "temperature": temperature,
            }
            if model is not None:
                payload["model"] = model
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens

            started_at = time.perf_counter()
            attempts = 0
            response: httpx.Response | None = None
            request_error: str | None = None
            current_retry_delay_seconds = max(0.0, retry_delay_seconds)
            while attempts <= max_retries:
                attempts += 1
                try:
                    response = http_client.post(f"{api_base}/rag/query", json=payload)
                    request_error = None
                    if not should_retry_error(response.status_code, response.text):
                        break
                except httpx.RequestError as exc:
                    response = None
                    request_error = str(exc)
                    if not should_retry_error(0, request_error):
                        break
                if attempts > max_retries:
                    break
                if current_retry_delay_seconds > 0:
                    time.sleep(current_retry_delay_seconds)
                current_retry_delay_seconds *= max(1.0, retry_backoff_multiplier)
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)

            if response is None:
                records.append(
                    score_answer(
                        question=question,
                        answer="",
                        sources=[],
                        status_code=0,
                        latency_ms=latency_ms,
                        top_k=top_k,
                        error=request_error or "Request failed before receiving a response.",
                        attempts=attempts,
                    )
                )
                if inter_request_delay_seconds > 0 and question_index < len(questions) - 1:
                    time.sleep(inter_request_delay_seconds)
                continue

            if response.status_code != 200:
                records.append(
                    score_answer(
                        question=question,
                        answer="",
                        sources=[],
                        status_code=response.status_code,
                        latency_ms=latency_ms,
                        top_k=top_k,
                        error=response.text,
                        attempts=attempts,
                    )
                )
                if inter_request_delay_seconds > 0 and question_index < len(questions) - 1:
                    time.sleep(inter_request_delay_seconds)
                continue

            body = response.json()
            sources = body.get("sources", [])
            if not isinstance(sources, list):
                sources = []
            usage = body.get("usage")
            if usage is not None and not isinstance(usage, dict):
                usage = None

            records.append(
                score_answer(
                    question=question,
                    answer=str(body.get("answer", "")),
                    sources=sources,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                    top_k=top_k,
                    model=body.get("model"),
                    finish_reason=body.get("finish_reason"),
                    usage=usage,
                    attempts=attempts,
                )
            )
            if inter_request_delay_seconds > 0 and question_index < len(questions) - 1:
                time.sleep(inter_request_delay_seconds)
    finally:
        if own_client:
            http_client.close()

    successful_records = [record for record in records if record["status_code"] == 200]
    passed_records = [record for record in successful_records if record["answer_passed"]]
    source_hit_records = [record for record in successful_records if record["source_hit"]]
    answer_keyword_hit_records = [
        record for record in successful_records if record["answer_keyword_hit"]
    ]
    citation_match_records = [
        record for record in successful_records if record["citation_match"]
    ]
    refused_records = [record for record in successful_records if record["refused"]]
    latencies = [float(record["latency_ms"]) for record in successful_records]
    failure_reason_counts = count_failure_reasons(records)
    error_category_counts = count_error_categories(records)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "api_base": api_base,
        "top_k": top_k,
        "total": len(records),
        "success_count": len(successful_records),
        "passed_count": len(passed_records),
        "overall_pass_rate": round(len(passed_records) / len(records), 4) if records else 0,
        "pass_rate": round(len(passed_records) / len(successful_records), 4)
        if successful_records
        else 0,
        "source_hit_count": len(source_hit_records),
        "source_hit_rate": round(len(source_hit_records) / len(successful_records), 4)
        if successful_records
        else 0,
        "answer_keyword_hit_count": len(answer_keyword_hit_records),
        "answer_keyword_hit_rate": round(
            len(answer_keyword_hit_records) / len(successful_records), 4
        )
        if successful_records
        else 0,
        "citation_match_count": len(citation_match_records),
        "citation_match_rate": round(len(citation_match_records) / len(successful_records), 4)
        if successful_records
        else 0,
        "refusal_count": len(refused_records),
        "failure_reason_counts": failure_reason_counts,
        "error_category_counts": error_category_counts,
        "retryable_failure_count": len(
            [
                record
                for record in records
                if not record["answer_passed"] and record.get("retryable")
            ]
        ),
        "recommendations": build_recommendations(
            failure_reason_counts=failure_reason_counts,
            error_category_counts=error_category_counts,
        ),
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
        "estimated_total_prompt_tokens": sum(
            int(record["estimated_prompt_tokens"]) for record in records
        ),
        "estimated_total_answer_tokens": sum(
            int(record["estimated_answer_tokens"]) for record in records
        ),
    }
    return {"summary": summary, "records": records}


def count_failure_reasons(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        for reason in record.get("failure_reasons", []):
            counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items()))


def count_error_categories(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        category = record.get("error_category")
        if category:
            counts[str(category)] = counts.get(str(category), 0) + 1
    return dict(sorted(counts.items()))


def build_recommendations(
    *,
    failure_reason_counts: dict[str, int],
    error_category_counts: dict[str, int],
) -> list[str]:
    recommendations: list[str] = []
    if any(
        category in error_category_counts
        for category in ("provider_transient_error", "rate_limited", "timeout", "request_error")
    ):
        recommendations.append(
            "Provider or transport failures were detected. Rerun in smaller batches, increase timeout, and use retry backoff/cooldown before judging answer quality."
        )
    if "configuration_error" in error_category_counts:
        recommendations.append(
            "Configuration errors were detected. Check local LLM/embedding API key and base URL before rerunning evaluation."
        )
    if "source_keywords_missing" in failure_reason_counts:
        recommendations.append(
            "Some retrieved sources missed expected keywords. Inspect retrieval results, knowledge coverage, top_k, chunking, and embedding index freshness."
        )
    if "answer_keywords_missing" in failure_reason_counts:
        recommendations.append(
            "Some answers missed expected keywords even when sources were present. Review prompt constraints, answer format, and model quality."
        )
    if "citation_mismatch" in failure_reason_counts:
        recommendations.append(
            "Citation mismatches were detected. Tighten the RAG prompt and validate that answers reference only returned source ids."
        )
    if "refused" in failure_reason_counts:
        recommendations.append(
            "Some answers refused despite evaluation expectations. Inspect whether sources are insufficient or the prompt is too conservative."
        )
    if not recommendations:
        recommendations.append("No dominant failure pattern detected in this run.")
    return recommendations


def write_json_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# RAG Answer Evaluation Report",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- api_base: `{summary['api_base']}`",
        f"- top_k: `{summary['top_k']}`",
        f"- total: `{summary['total']}`",
        f"- success_count: `{summary['success_count']}`",
        f"- passed_count: `{summary['passed_count']}`",
        f"- overall_pass_rate: `{summary['overall_pass_rate']}`",
        f"- pass_rate: `{summary['pass_rate']}`",
        f"- source_hit_rate: `{summary['source_hit_rate']}`",
        f"- answer_keyword_hit_rate: `{summary['answer_keyword_hit_rate']}`",
        f"- citation_match_rate: `{summary['citation_match_rate']}`",
        f"- refusal_count: `{summary['refusal_count']}`",
        f"- retryable_failure_count: `{summary['retryable_failure_count']}`",
        f"- avg_latency_ms: `{summary['avg_latency_ms']}`",
        f"- estimated_total_prompt_tokens: `{summary['estimated_total_prompt_tokens']}`",
        f"- estimated_total_answer_tokens: `{summary['estimated_total_answer_tokens']}`",
        f"- failure_reason_counts: `{json.dumps(summary['failure_reason_counts'], ensure_ascii=False)}`",
        f"- error_category_counts: `{json.dumps(summary['error_category_counts'], ensure_ascii=False)}`",
        "",
        "## Recommendations",
        "",
        *[f"- {recommendation}" for recommendation in summary["recommendations"]],
        "",
        "## Records",
        "",
        "| id | pass | status | error_category | attempts | latency_ms | sources | source_hit | answer_hits | citations | refused | primary_failure | answer_preview |",
        "|---|---:|---:|---|---:|---:|---:|---:|---|---|---:|---|---|",
    ]
    for record in report["records"]:
        lines.append(
            "| {id} | {passed} | {status} | {error_category} | {attempts} | {latency} | {source_count} | {source_hit} | {answer_hits} | {citations} | {refused} | {primary_failure} | {preview} |".format(
                id=record["id"],
                passed="yes" if record["answer_passed"] else "no",
                status=record["status_code"],
                error_category=record.get("error_category") or "",
                attempts=record["attempts"],
                latency=record["latency_ms"],
                source_count=record["source_count"],
                source_hit="yes" if record["source_hit"] else "no",
                answer_hits=", ".join(record["answer_keyword_hits"]),
                citations=", ".join(str(item) for item in record["citation_ids"]),
                refused="yes" if record["refused"] else "no",
                primary_failure=record.get("primary_failure_reason") or "",
                preview=_markdown_cell(record["answer_preview"]),
            )
        )

    failed_records = [record for record in report["records"] if not record["answer_passed"]]
    if failed_records:
        lines.extend(["", "## Failed Or Risky Cases", ""])
        for record in failed_records:
            reasons = _failure_reasons(record)
            lines.extend(
                [
                    f"### {record['id']}",
                    "",
                    f"- question: `{_markdown_cell(record['question'])}`",
                    f"- reasons: {', '.join(reasons) if reasons else 'unknown'}",
                    f"- error_category: `{record.get('error_category') or ''}`",
                    f"- retryable: `{record.get('retryable')}`",
                    f"- source_keyword_hits: `{', '.join(record['source_keyword_hits'])}`",
                    f"- answer_keyword_hits: `{', '.join(record['answer_keyword_hits'])}`",
                    f"- citation_ids: `{', '.join(str(item) for item in record['citation_ids'])}`",
                    f"- answer: {_markdown_cell(record['answer'])}",
                    "",
                ]
            )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _failure_reasons(record: dict[str, Any]) -> list[str]:
    reasons = record.get("failure_reasons")
    if isinstance(reasons, list):
        return [str(reason) for reason in reasons]
    return []


def _markdown_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")[:500]


__all__ = [
    "build_recommendations",
    "classify_error_category",
    "count_failure_reasons",
    "detect_refusal",
    "evaluate_answer_questions",
    "extract_citation_ids",
    "find_text_keyword_hits",
    "load_questions",
    "score_answer",
    "write_json_report",
    "write_markdown_report",
]
