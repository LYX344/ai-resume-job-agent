from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.answer import (
    DEFAULT_API_BASE_URL,
    evaluate_answer_questions,
    load_questions,
    write_json_report,
    write_markdown_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run RAG answer quality evaluation.")
    parser.add_argument(
        "--questions",
        type=Path,
        default=Path("data/eval/rag_questions.json"),
        help="Path to the JSON question set.",
    )
    parser.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE_URL,
        help="API base URL, for example http://127.0.0.1:8025/api/v1.",
    )
    parser.add_argument("--top-k", type=int, default=3, help="Number of chunks to retrieve.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/eval/runs"),
        help="Directory for JSON and Markdown reports.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--model", default=None)
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help="Retry count for transient 5xx responses from the RAG/LLM path.",
    )
    parser.add_argument(
        "--retry-delay-seconds",
        type=float,
        default=0.5,
        help="Initial delay between retries for transient failures.",
    )
    parser.add_argument(
        "--retry-backoff-multiplier",
        type=float,
        default=1.5,
        help="Multiplier applied to retry delay after each failed attempt.",
    )
    parser.add_argument(
        "--inter-request-delay-seconds",
        type=float,
        default=0.0,
        help="Cooldown between evaluated questions. Useful for unstable local LLM proxies.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Skip the first N questions before applying --limit. Useful for batched eval runs.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Evaluate only the first N questions. 0 means all questions.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    questions = load_questions(args.questions)
    if args.offset > 0:
        questions = questions[args.offset :]
    if args.limit > 0:
        questions = questions[: args.limit]

    report = evaluate_answer_questions(
        questions=questions,
        api_base=args.api_base,
        top_k=args.top_k,
        timeout_seconds=args.timeout_seconds,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        max_retries=args.max_retries,
        retry_delay_seconds=args.retry_delay_seconds,
        retry_backoff_multiplier=args.retry_backoff_multiplier,
        inter_request_delay_seconds=args.inter_request_delay_seconds,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = args.output_dir / f"answer_eval_{timestamp}.json"
    markdown_path = args.output_dir / f"answer_eval_{timestamp}.md"
    write_json_report(report, json_path)
    write_markdown_report(report, markdown_path)

    summary = report["summary"]
    print(f"questions={summary['total']}")
    print(f"success={summary['success_count']}")
    print(f"passed={summary['passed_count']}")
    print(f"overall_pass_rate={summary['overall_pass_rate']}")
    print(f"pass_rate={summary['pass_rate']}")
    print(f"citation_match_rate={summary['citation_match_rate']}")
    print(f"answer_keyword_hit_rate={summary['answer_keyword_hit_rate']}")
    print(f"retryable_failure_count={summary['retryable_failure_count']}")
    print(f"failure_reason_counts={summary['failure_reason_counts']}")
    print(f"error_category_counts={summary['error_category_counts']}")
    print(f"avg_latency_ms={summary['avg_latency_ms']}")
    print(f"json_report={json_path}")
    print(f"markdown_report={markdown_path}")


if __name__ == "__main__":
    main()
