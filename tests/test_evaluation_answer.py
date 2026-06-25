import json
from pathlib import Path

import httpx

from app.evaluation.answer import (
    EvalQuestion,
    classify_error_category,
    detect_refusal,
    evaluate_answer_questions,
    extract_citation_ids,
    find_text_keyword_hits,
    score_answer,
    write_json_report,
    write_markdown_report,
)


def test_extract_citation_ids_returns_sorted_unique_ids() -> None:
    assert extract_citation_ids("参考 [2] 和 [1]，再次引用 [2]。") == [1, 2]


def test_find_text_keyword_hits_is_case_insensitive() -> None:
    assert find_text_keyword_hits(["Redis", "RAG"], "redis 可以支持 rag。") == [
        "Redis",
        "RAG",
    ]


def test_detect_refusal_finds_no_context_answers() -> None:
    assert detect_refusal("我没有在知识库中检索到相关内容。")
    assert not detect_refusal("Redis 可以保存 session。[1]")


def test_classify_error_category_detects_configuration_and_transient_errors() -> None:
    assert (
        classify_error_category(503, "LLM_API_KEY is not configured.")
        == "configuration_error"
    )
    assert classify_error_category(502, "empty upstream response") == "provider_transient_error"
    assert classify_error_category(429, "rate limit") == "rate_limited"
    assert classify_error_category(0, "connection refused") == "request_error"


def test_score_answer_passes_grounded_answer_with_valid_citation() -> None:
    question = EvalQuestion(
        id="q001",
        question="Redis 做什么？",
        expected_keywords=["Redis", "session"],
    )

    record = score_answer(
        question=question,
        answer="Redis 可以保存 session，并支持向量检索。[1]",
        sources=[
            {
                "source_id": 1,
                "key": "doc:abc:0",
                "content": "Redis 可以保存 session，也可以做向量检索。",
                "metadata": {"source": "notes.md"},
                "distance": 0.12,
            }
        ],
        status_code=200,
        latency_ms=12.3,
        top_k=1,
    )

    assert record["answer_passed"] is True
    assert record["source_hit"] is True
    assert record["answer_keyword_hits"] == ["Redis", "session"]
    assert record["citation_match"] is True
    assert record["attempts"] == 1
    assert record["failure_reasons"] == []
    assert record["primary_failure_reason"] is None
    assert record["error_category"] is None


def test_score_answer_fails_invalid_citation() -> None:
    question = EvalQuestion(
        id="q001",
        question="Redis 做什么？",
        expected_keywords=["Redis"],
    )

    record = score_answer(
        question=question,
        answer="Redis 可以做缓存。[2]",
        sources=[
            {
                "source_id": 1,
                "key": "doc:abc:0",
                "content": "Redis 可以做缓存。",
                "metadata": {},
                "distance": 0.12,
            }
        ],
        status_code=200,
        latency_ms=12.3,
        top_k=1,
    )

    assert record["answer_passed"] is False
    assert record["invalid_citation_ids"] == [2]
    assert record["citation_match"] is False
    assert "citation_mismatch" in record["failure_reasons"]


def test_evaluate_answer_questions_records_answer_sources_and_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/rag/query"
        payload = json.loads(request.content)
        assert payload["query"] == "Redis 做什么？"
        assert payload["temperature"] == 0
        return httpx.Response(
            200,
            json={
                "answer": "Redis 可以保存 session，也可以做向量检索。[1]",
                "model": "test-model",
                "sources": [
                    {
                        "source_id": 1,
                        "key": "doc:abc:0",
                        "content": "Redis 可以保存 session，也可以做向量检索。",
                        "metadata": {"source": "notes.md"},
                        "distance": 0.12,
                    }
                ],
                "finish_reason": "stop",
                "usage": {"total_tokens": 42},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    report = evaluate_answer_questions(
        questions=[
            EvalQuestion(
                id="q001",
                question="Redis 做什么？",
                expected_keywords=["Redis", "session"],
            )
        ],
        api_base="http://testserver/api/v1",
        top_k=1,
        client=client,
    )

    assert report["summary"]["total"] == 1
    assert report["summary"]["success_count"] == 1
    assert report["summary"]["passed_count"] == 1
    assert report["summary"]["overall_pass_rate"] == 1
    assert report["summary"]["pass_rate"] == 1
    assert report["summary"]["citation_match_rate"] == 1
    assert report["records"][0]["model"] == "test-model"
    assert report["records"][0]["sources"][0]["source"] == "notes.md"
    assert report["summary"]["failure_reason_counts"] == {}
    assert report["summary"]["error_category_counts"] == {}


def test_evaluate_answer_questions_records_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="LLM_API_KEY is not configured.")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    report = evaluate_answer_questions(
        questions=[
            EvalQuestion(id="q001", question="Redis 做什么？", expected_keywords=["Redis"])
        ],
        api_base="http://testserver/api/v1",
        top_k=1,
        client=client,
    )

    assert report["summary"]["success_count"] == 0
    assert report["summary"]["passed_count"] == 0
    assert report["records"][0]["status_code"] == 503
    assert "LLM_API_KEY" in report["records"][0]["error"]
    assert report["records"][0]["error_category"] == "configuration_error"
    assert report["records"][0]["retryable"] is False
    assert report["summary"]["error_category_counts"] == {"configuration_error": 1}


def test_evaluate_answer_questions_does_not_retry_configuration_errors() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(503, text="LLM_API_KEY is not configured.")

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    report = evaluate_answer_questions(
        questions=[
            EvalQuestion(id="q001", question="Redis 做什么？", expected_keywords=["Redis"])
        ],
        api_base="http://testserver/api/v1",
        top_k=1,
        max_retries=3,
        retry_delay_seconds=0,
        client=client,
    )

    assert call_count == 1
    assert report["records"][0]["attempts"] == 1
    assert report["records"][0]["error_category"] == "configuration_error"


def test_evaluate_answer_questions_retries_transient_5xx() -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(502, text="empty upstream response")
        return httpx.Response(
            200,
            json={
                "answer": "Redis 可以保存 session。[1]",
                "sources": [
                    {
                        "source_id": 1,
                        "key": "doc:abc:0",
                        "content": "Redis 可以保存 session。",
                        "metadata": {},
                        "distance": 0.12,
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    report = evaluate_answer_questions(
        questions=[
            EvalQuestion(
                id="q001",
                question="Redis 做什么？",
                expected_keywords=["Redis", "session"],
            )
        ],
        api_base="http://testserver/api/v1",
        top_k=1,
        max_retries=1,
        retry_delay_seconds=0,
        client=client,
    )

    assert call_count == 2
    assert report["summary"]["passed_count"] == 1
    assert report["records"][0]["attempts"] == 2
    assert report["summary"]["retryable_failure_count"] == 0


def test_evaluate_answer_questions_records_request_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    report = evaluate_answer_questions(
        questions=[
            EvalQuestion(id="q001", question="Redis 做什么？", expected_keywords=["Redis"])
        ],
        api_base="http://testserver/api/v1",
        top_k=1,
        max_retries=1,
        retry_delay_seconds=0,
        client=client,
    )

    assert report["summary"]["success_count"] == 0
    assert report["records"][0]["status_code"] == 0
    assert report["records"][0]["attempts"] == 2
    assert report["records"][0]["error_category"] == "request_error"
    assert report["records"][0]["retryable"] is True


def test_write_answer_reports_create_json_and_markdown(tmp_path: Path) -> None:
    report = {
        "summary": {
            "generated_at": "2026-06-15T12:00:00+00:00",
            "api_base": "http://127.0.0.1:8025/api/v1",
            "top_k": 1,
            "total": 1,
            "success_count": 1,
            "passed_count": 1,
            "overall_pass_rate": 1,
            "pass_rate": 1,
            "source_hit_rate": 1,
            "answer_keyword_hit_rate": 1,
            "citation_match_rate": 1,
            "refusal_count": 0,
            "retryable_failure_count": 0,
            "failure_reason_counts": {},
            "error_category_counts": {},
            "recommendations": ["No dominant failure pattern detected in this run."],
            "avg_latency_ms": 12.3,
            "estimated_total_prompt_tokens": 10,
            "estimated_total_answer_tokens": 4,
        },
        "records": [
            {
                "id": "q001",
                "question": "Redis 做什么？",
                "answer_passed": True,
                "status_code": 200,
                "attempts": 1,
                "latency_ms": 12.3,
                "source_count": 1,
                "source_hit": True,
                "answer_keyword_hits": ["Redis"],
                "citation_ids": [1],
                "refused": False,
                "failure_reasons": [],
                "primary_failure_reason": None,
                "error_category": None,
                "retryable": False,
                "answer_preview": "Redis 可以做缓存。[1]",
                "source_keyword_hits": ["Redis"],
                "answer": "Redis 可以做缓存。[1]",
            }
        ],
    }
    json_path = tmp_path / "answer.json"
    markdown_path = tmp_path / "answer.md"

    write_json_report(report, json_path)
    write_markdown_report(report, markdown_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["total"] == 1
    assert "RAG Answer Evaluation Report" in markdown_path.read_text(encoding="utf-8")
