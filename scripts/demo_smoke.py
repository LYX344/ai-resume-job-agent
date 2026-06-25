from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx


DEFAULT_API_BASE_URL = "http://127.0.0.1:8025/api/v1"


@dataclass
class DemoStep:
    name: str
    status: str
    latency_ms: float
    summary: str
    data: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a deterministic local demo smoke test for AI Resume Job Agent."
    )
    parser.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE_URL,
        help="API base URL, for example http://127.0.0.1:8025/api/v1.",
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=Path("README.md"),
        help="Markdown file used for async upload and file summary demo.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/demo/runs"),
        help="Directory for JSON and Markdown demo reports.",
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=0.25)
    return parser.parse_args()


def normalize_api_base(api_base: str) -> str:
    normalized = api_base.strip().rstrip("/")
    if not normalized:
        raise ValueError("api_base must not be empty.")
    return normalized


def preview_text(value: Any, *, limit: int = 160) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def run_step(name: str, callback: Callable[[], tuple[str, dict[str, Any]]]) -> DemoStep:
    started_at = time.perf_counter()
    try:
        summary, data = callback()
        status = "passed"
    except Exception as exc:
        summary = str(exc)
        data = {"error_type": type(exc).__name__}
        status = "failed"
    latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
    return DemoStep(
        name=name,
        status=status,
        latency_ms=latency_ms,
        summary=summary,
        data=data,
    )


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    **kwargs: Any,
) -> dict[str, Any]:
    response = client.request(method, url, **kwargs)
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict):
        raise ValueError(f"Expected JSON object from {url}.")
    return body


def wait_for_index_task(
    client: httpx.Client,
    api_base: str,
    task_id: str,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = request_json(client, "GET", f"{api_base}/documents/tasks/{task_id}")
        status = latest.get("status")
        if status == "done":
            return latest
        if status == "failed":
            raise RuntimeError(f"Index task failed: {latest.get('error_message')}")
        time.sleep(poll_interval_seconds)
    raise TimeoutError(f"Index task {task_id} did not finish within {timeout_seconds} seconds.")


def upload_readme_and_wait(
    client: httpx.Client,
    api_base: str,
    readme_path: Path,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> tuple[str, dict[str, Any]]:
    if not readme_path.exists():
        raise FileNotFoundError(f"README demo file not found: {readme_path}")
    with readme_path.open("rb") as file_obj:
        task = request_json(
            client,
            "POST",
            f"{api_base}/documents/upload/async",
            files={"file": (readme_path.name, file_obj, "text/markdown")},
        )
    task_id = str(task["task_id"])
    done_task = wait_for_index_task(
        client,
        api_base,
        task_id,
        timeout_seconds=timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
    )
    summary = (
        f"indexed {done_task.get('chunk_count', 0)} chunks from "
        f"{done_task.get('file_name', readme_path.name)}"
    )
    return summary, {
        "task_id": task_id,
        "status": done_task.get("status"),
        "document_id": done_task.get("document_id"),
        "chunk_count": done_task.get("chunk_count"),
    }


def agent_step_data(response: dict[str, Any]) -> dict[str, Any]:
    steps = response.get("steps", [])
    step_names = []
    if isinstance(steps, list):
        step_names = [str(step.get("name")) for step in steps if isinstance(step, dict)]
    return {
        "intent": response.get("intent"),
        "used_knowledge_base": response.get("used_knowledge_base"),
        "memory_used": response.get("memory_used"),
        "answer_preview": preview_text(response.get("answer")),
        "steps": step_names,
    }


def build_report(api_base: str, steps: list[DemoStep]) -> dict[str, Any]:
    passed = sum(1 for step in steps if step.status == "passed")
    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "api_base": api_base,
            "total": len(steps),
            "passed": passed,
            "failed": len(steps) - passed,
        },
        "steps": [asdict(step) for step in steps],
    }


def write_json_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = report["summary"]
    lines = [
        "# Demo Smoke Report",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- api_base: `{summary['api_base']}`",
        f"- total: `{summary['total']}`",
        f"- passed: `{summary['passed']}`",
        f"- failed: `{summary['failed']}`",
        "",
        "| step | status | latency_ms | summary |",
        "|---|---|---:|---|",
    ]
    for step in report["steps"]:
        lines.append(
            "| {name} | {status} | {latency} | {summary} |".format(
                name=step["name"],
                status=step["status"],
                latency=step["latency_ms"],
                summary=str(step["summary"]).replace("|", "\\|"),
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    api_base = normalize_api_base(args.api_base)
    readme_path = args.readme
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"demo-smoke-{timestamp}"
    steps: list[DemoStep] = []

    with httpx.Client(timeout=args.timeout_seconds) as client:
        steps.append(
            run_step(
                "health",
                lambda: (
                    "backend health ok",
                    request_json(client, "GET", f"{api_base}/health"),
                ),
            )
        )
        steps.append(
            run_step(
                "redis_health",
                lambda: (
                    "redis health ok",
                    request_json(client, "GET", f"{api_base}/health/redis"),
                ),
            )
        )
        steps.append(
            run_step(
                "async_upload_readme",
                lambda: upload_readme_and_wait(
                    client,
                    api_base,
                    readme_path,
                    timeout_seconds=args.timeout_seconds,
                    poll_interval_seconds=args.poll_interval_seconds,
                ),
            )
        )
        steps.append(
            run_step(
                "document_search",
                lambda: _search_documents(client, api_base, args.top_k),
            )
        )
        steps.append(
            run_step(
                "agent_calculator",
                lambda: _run_agent(
                    client,
                    api_base,
                    {"query": "请计算 2 + 3 * 4 等于多少？", "use_knowledge_base": False},
                ),
            )
        )
        steps.append(
            run_step(
                "agent_todo",
                lambda: _run_agent(
                    client,
                    api_base,
                    {
                        "query": "帮我生成待办：复习 Redis、写简历、提交周报",
                        "use_knowledge_base": False,
                    },
                ),
            )
        )
        steps.append(
            run_step(
                "agent_summarize_file",
                lambda: _run_agent(
                    client,
                    api_base,
                    {"query": "请总结 README.md", "use_knowledge_base": False},
                ),
            )
        )
        steps.append(
            run_step(
                "agent_weekly_report",
                lambda: _run_agent(
                    client,
                    api_base,
                    {
                        "query": (
                            "帮我写周报：本周完成：接入 Redis、补充测试；"
                            "问题：Docker Hub 暂时无法访问；下周计划：补完整容器烟测"
                        ),
                        "use_knowledge_base": False,
                    },
                ),
            )
        )
        steps.append(
            run_step(
                "agent_memory_update",
                lambda: _run_agent(
                    client,
                    api_base,
                    {
                        "session_id": session_id,
                        "query": "请记住：我演示项目时先讲 Redis、RAG 和 Agent 工具调用",
                        "use_knowledge_base": False,
                    },
                ),
            )
        )

    report = build_report(api_base, steps)
    json_path = args.output_dir / f"demo_smoke_{timestamp}.json"
    markdown_path = args.output_dir / f"demo_smoke_{timestamp}.md"
    write_json_report(report, json_path)
    write_markdown_report(report, markdown_path)

    summary = report["summary"]
    print(f"total={summary['total']}")
    print(f"passed={summary['passed']}")
    print(f"failed={summary['failed']}")
    print(f"json_report={json_path}")
    print(f"markdown_report={markdown_path}")
    if summary["failed"]:
        raise SystemExit(1)


def _search_documents(
    client: httpx.Client,
    api_base: str,
    top_k: int,
) -> tuple[str, dict[str, Any]]:
    body = request_json(
        client,
        "POST",
        f"{api_base}/documents/search",
        json={"query": "Redis RAG Agent 记忆 工具调用", "top_k": top_k},
    )
    results = body.get("results", [])
    result_count = len(results) if isinstance(results, list) else 0
    top_source = None
    if isinstance(results, list) and results:
        metadata = results[0].get("metadata", {})
        if isinstance(metadata, dict):
            top_source = metadata.get("source") or metadata.get("file_name")
    return (
        f"retrieved {result_count} chunks",
        {"result_count": result_count, "top_source": top_source},
    )


def _run_agent(
    client: httpx.Client,
    api_base: str,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    response = request_json(client, "POST", f"{api_base}/agent/run", json=payload)
    data = agent_step_data(response)
    return f"intent={data['intent']}", data


if __name__ == "__main__":
    main()
