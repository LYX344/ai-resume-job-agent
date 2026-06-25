from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.retrieval import (
    DEFAULT_API_BASE_URL,
    evaluate_questions,
    load_questions,
    write_json_report,
    write_markdown_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Redis vector retrieval evaluation.")
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
        "--collection",
        default=None,
        help="Restrict retrieval to a knowledge-base collection, e.g. resume or project_docs.",
    )
    parser.add_argument(
        "--rewrite",
        action="store_true",
        help="Enable LLM query rewriting before retrieval.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/eval/runs"),
        help="Directory for JSON and Markdown reports.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    questions = load_questions(args.questions)
    report = evaluate_questions(
        questions=questions,
        api_base=args.api_base,
        top_k=args.top_k,
        collection=args.collection,
        rewrite=args.rewrite,
        timeout_seconds=args.timeout_seconds,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = args.output_dir / f"retrieval_eval_{timestamp}.json"
    markdown_path = args.output_dir / f"retrieval_eval_{timestamp}.md"
    write_json_report(report, json_path)
    write_markdown_report(report, markdown_path)

    summary = report["summary"]
    print(f"questions={summary['total']}")
    print(f"success={summary['success_count']}")
    print(f"hit_rate={summary['hit_rate']}")
    print(f"avg_latency_ms={summary['avg_latency_ms']}")
    print(f"json_report={json_path}")
    print(f"markdown_report={markdown_path}")


if __name__ == "__main__":
    main()
