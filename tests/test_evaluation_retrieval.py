import json
from pathlib import Path

import httpx

from app.evaluation.retrieval import (
    EvalQuestion,
    estimate_token_count,
    evaluate_questions,
    find_keyword_hits,
    load_questions,
    write_json_report,
    write_markdown_report,
)


def test_load_questions_reads_json_question_set(tmp_path: Path) -> None:
    question_path = tmp_path / "questions.json"
    question_path.write_text(
        json.dumps(
            [
                {
                    "id": "q001",
                    "question": "Redis 做什么？",
                    "expected_keywords": ["Redis"],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    questions = load_questions(question_path)

    assert questions == [
        EvalQuestion(
            id="q001",
            question="Redis 做什么？",
            expected_keywords=["Redis"],
            notes="",
        )
    ]


def test_find_keyword_hits_scans_content_and_metadata() -> None:
    hits = find_keyword_hits(
        ["Redis", "session"],
        [
            {
                "content": "向量检索",
                "metadata": {"source": "redis-session-notes.md"},
            }
        ],
    )

    assert hits == ["Redis", "session"]


def test_evaluate_questions_records_retrieved_chunks_and_summary() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/documents/search"
        return httpx.Response(
            200,
            json={
                "query": "Redis 做什么？",
                "top_k": 1,
                "results": [
                    {
                        "key": "doc:abc:0",
                        "content": "Redis 可以保存 session，也可以做向量检索。",
                        "metadata": {"source": "notes.md"},
                        "distance": 0.12,
                    }
                ],
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://testserver")
    report = evaluate_questions(
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
    assert report["summary"]["hit_count"] == 1
    assert report["records"][0]["hit"] is True
    assert report["records"][0]["keyword_hits"] == ["Redis", "session"]
    assert report["records"][0]["retrieved_chunks"][0]["source"] == "notes.md"
    assert report["records"][0]["answer_status"] == "not_generated_retrieval_only"


def test_write_reports_create_json_and_markdown(tmp_path: Path) -> None:
    report = {
        "summary": {
            "generated_at": "2026-06-14T00:00:00+00:00",
            "api_base": "http://127.0.0.1:8025/api/v1",
            "top_k": 1,
            "total": 1,
            "success_count": 1,
            "hit_count": 1,
            "hit_rate": 1,
            "avg_latency_ms": 12.3,
            "estimated_total_prompt_tokens": 10,
        },
        "records": [
            {
                "id": "q001",
                "hit": True,
                "latency_ms": 12.3,
                "keyword_hits": ["Redis"],
                "retrieved_chunks": [{"source": "notes.md"}],
            }
        ],
    }
    json_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"

    write_json_report(report, json_path)
    write_markdown_report(report, markdown_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"]["total"] == 1
    assert "Retrieval Evaluation Report" in markdown_path.read_text(encoding="utf-8")


def test_estimate_token_count_is_rough_positive_estimate() -> None:
    assert estimate_token_count("") == 0
    assert estimate_token_count("abcd") == 1
    assert estimate_token_count("abcde") == 2
