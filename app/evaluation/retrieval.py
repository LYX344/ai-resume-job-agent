import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


DEFAULT_API_BASE_URL = "http://127.0.0.1:8025/api/v1"


@dataclass(frozen=True)
class EvalQuestion:
    id: str
    question: str
    expected_keywords: list[str]
    notes: str = ""


def load_questions(path: Path) -> list[EvalQuestion]:
    raw_data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw_data, list):
        raise ValueError("Evaluation questions file must contain a JSON list.")

    questions: list[EvalQuestion] = []
    for item in raw_data:
        if not isinstance(item, dict):
            raise ValueError("Each evaluation question must be a JSON object.")
        questions.append(
            EvalQuestion(
                id=str(item["id"]),
                question=str(item["question"]),
                expected_keywords=[str(keyword) for keyword in item.get("expected_keywords", [])],
                notes=str(item.get("notes", "")),
            )
        )
    return questions


def estimate_token_count(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def normalize_api_base(api_base: str) -> str:
    normalized = api_base.strip().rstrip("/")
    if not normalized:
        raise ValueError("api_base must not be empty.")
    return normalized


def find_keyword_hits(expected_keywords: list[str], results: list[dict[str, Any]]) -> list[str]:
    haystack_parts: list[str] = []
    for result in results:
        haystack_parts.append(str(result.get("content", "")))
        haystack_parts.append(json.dumps(result.get("metadata", {}), ensure_ascii=False))
    haystack = "\n".join(haystack_parts).lower()
    return [keyword for keyword in expected_keywords if keyword.lower() in haystack]


def compact_result(result: dict[str, Any], rank: int) -> dict[str, Any]:
    metadata = result.get("metadata", {})
    source = "unknown"
    if isinstance(metadata, dict):
        source = str(metadata.get("source") or metadata.get("file_name") or "unknown")

    content = str(result.get("content", ""))
    return {
        "rank": rank,
        "key": str(result.get("key", "")),
        "source": source,
        "distance": result.get("distance"),
        "content_preview": content[:240],
    }


def evaluate_questions(
    *,
    questions: list[EvalQuestion],
    api_base: str = DEFAULT_API_BASE_URL,
    top_k: int = 3,
    collection: str | None = None,
    rewrite: bool = False,
    timeout_seconds: float = 10.0,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    api_base = normalize_api_base(api_base)
    own_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds)

    records: list[dict[str, Any]] = []
    try:
        for question in questions:
            started_at = time.perf_counter()
            payload: dict[str, Any] = {"query": question.question, "top_k": top_k}
            if collection:
                payload["collection"] = collection
            if rewrite:
                payload["rewrite"] = True
            response = http_client.post(
                f"{api_base}/documents/search",
                json=payload,
            )
            latency_ms = round((time.perf_counter() - started_at) * 1000, 2)

            record: dict[str, Any] = {
                "id": question.id,
                "question": question.question,
                "expected_keywords": question.expected_keywords,
                "notes": question.notes,
                "top_k": top_k,
                "status_code": response.status_code,
                "latency_ms": latency_ms,
                "answer": None,
                "answer_status": "not_generated_retrieval_only",
                "retrieved_chunks": [],
                "keyword_hits": [],
                "hit": False,
                "estimated_prompt_tokens": estimate_token_count(question.question),
            }

            if response.status_code != 200:
                record["error"] = response.text
                records.append(record)
                continue

            body = response.json()
            results = body.get("results", [])
            if not isinstance(results, list):
                results = []

            keyword_hits = find_keyword_hits(question.expected_keywords, results)
            retrieved_chunks = [compact_result(result, index + 1) for index, result in enumerate(results)]
            retrieved_text = "\n".join(str(result.get("content", "")) for result in results)

            record.update(
                {
                    "result_count": len(results),
                    "retrieved_chunks": retrieved_chunks,
                    "keyword_hits": keyword_hits,
                    "hit": bool(keyword_hits),
                    "estimated_prompt_tokens": estimate_token_count(
                        f"{question.question}\n{retrieved_text}"
                    ),
                }
            )
            records.append(record)
    finally:
        if own_client:
            http_client.close()

    successful_records = [record for record in records if record["status_code"] == 200]
    hit_records = [record for record in successful_records if record["hit"]]
    latencies = [float(record["latency_ms"]) for record in successful_records]
    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "api_base": api_base,
        "top_k": top_k,
        "collection": collection,
        "rewrite": rewrite,
        "total": len(records),
        "success_count": len(successful_records),
        "hit_count": len(hit_records),
        "hit_rate": round(len(hit_records) / len(successful_records), 4) if successful_records else 0,
        "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
        "estimated_total_prompt_tokens": sum(
            int(record["estimated_prompt_tokens"]) for record in records
        ),
    }
    return {"summary": summary, "records": records}


def write_json_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# Retrieval Evaluation Report",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- api_base: `{summary['api_base']}`",
        f"- top_k: `{summary['top_k']}`",
        f"- total: `{summary['total']}`",
        f"- success_count: `{summary['success_count']}`",
        f"- hit_count: `{summary['hit_count']}`",
        f"- hit_rate: `{summary['hit_rate']}`",
        f"- avg_latency_ms: `{summary['avg_latency_ms']}`",
        f"- estimated_total_prompt_tokens: `{summary['estimated_total_prompt_tokens']}`",
        "",
        "| id | hit | latency_ms | keyword_hits | top_source |",
        "|---|---:|---:|---|---|",
    ]
    for record in report["records"]:
        top_source = ""
        if record["retrieved_chunks"]:
            top_source = str(record["retrieved_chunks"][0]["source"])
        lines.append(
            "| {id} | {hit} | {latency} | {keywords} | {source} |".format(
                id=record["id"],
                hit="yes" if record["hit"] else "no",
                latency=record["latency_ms"],
                keywords=", ".join(record["keyword_hits"]),
                source=top_source,
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def question_to_dict(question: EvalQuestion) -> dict[str, Any]:
    return asdict(question)
