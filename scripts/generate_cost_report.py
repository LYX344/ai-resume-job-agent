from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.cost import COST_OPTIMIZATION_NOTES, build_cost_report


def find_latest_answer_eval(runs_dir: Path) -> Path | None:
    candidates = sorted(runs_dir.glob("answer_eval_*.json"))
    return candidates[-1] if candidates else None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a RAG/LLM cost report from an answer eval report."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help="Answer eval JSON report. Defaults to the latest in --runs-dir.",
    )
    parser.add_argument("--runs-dir", type=Path, default=Path("data/eval/runs"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/eval/runs"))
    parser.add_argument("--prompt-price-per-1k", type=float, default=0.0)
    parser.add_argument("--completion-price-per-1k", type=float, default=0.0)
    return parser.parse_args()


def render_markdown(report: dict, *, source_path: Path) -> str:
    lines = [
        "# RAG/LLM 成本报告",
        "",
        f"- 来源报告: `{source_path.name}`",
        f"- token 来源: `{report['token_source']}`",
        f"- 评测题数: `{report['total_questions']}`",
        f"- 总调用次数(含重试): `{report['total_calls']}`",
        f"- 重试次数: `{report['retry_calls']}`",
        f"- 成功调用: `{report['success_calls']}`",
        f"- 平均延迟(ms): `{report['avg_latency_ms']}`",
        f"- prompt tokens: `{report['total_prompt_tokens']}`",
        f"- completion tokens: `{report['total_completion_tokens']}`",
        f"- reasoning tokens: `{report['total_reasoning_tokens']}`",
        f"- total tokens: `{report['total_tokens']}`",
        f"- 单价 prompt(/1K): `{report['prompt_price_per_1k']}`",
        f"- 单价 completion(/1K): `{report['completion_price_per_1k']}`",
        f"- prompt 成本: `{report['prompt_cost']}`",
        f"- completion 成本: `{report['completion_cost']}`",
        f"- 总成本: `{report['total_cost']}`",
        f"- 平均每题成本: `{report['avg_cost_per_question']}`",
        f"- 平均每次调用成本: `{report['avg_cost_per_call']}`",
        f"- 重试成本: `{report['retry_cost']}`",
        "",
        "## 成本优化策略",
        "",
        *[f"- {note}" for note in COST_OPTIMIZATION_NOTES],
        "",
        "## 说明",
        "",
        "- 本地反代通常免费，默认单价为 0；如需估算云端成本，用 "
        "`--prompt-price-per-1k` / `--completion-price-per-1k` 传入每 1K token 价格。",
        "- reasoning tokens 计入 completion，推理模型（如 deepseek）该项可能很大。",
        "- 重试成本按 平均每次调用成本 × 重试次数 估算，用于体现失败重试对成本的影响。",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    input_path = args.input or find_latest_answer_eval(args.runs_dir)
    if input_path is None or not input_path.exists():
        print("No answer eval report found.")
        return

    eval_report = json.loads(input_path.read_text(encoding="utf-8"))
    report = build_cost_report(
        eval_report,
        prompt_price_per_1k=args.prompt_price_per_1k,
        completion_price_per_1k=args.completion_price_per_1k,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / f"cost_report_{timestamp}.json"
    markdown_path = args.output_dir / f"cost_report_{timestamp}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown_path.write_text(
        render_markdown(report, source_path=input_path), encoding="utf-8"
    )

    print(f"token_source={report['token_source']}")
    print(f"total_questions={report['total_questions']}")
    print(f"total_calls={report['total_calls']}")
    print(f"total_tokens={report['total_tokens']}")
    print(f"total_reasoning_tokens={report['total_reasoning_tokens']}")
    print(f"total_cost={report['total_cost']}")
    print(f"json_report={json_path}")
    print(f"markdown_report={markdown_path}")


if __name__ == "__main__":
    main()
