from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("data/demo/packages")
DEFAULT_ASSETS_DIR = Path("data/demo/assets")

SCREENSHOT_CHECKLIST = [
    {
        "file_name": "01-readme-overview.png",
        "target": "README.md",
        "purpose": "Show project positioning, stack, and current status.",
    },
    {
        "file_name": "02-fastapi-docs.png",
        "target": "http://127.0.0.1:8025/docs",
        "purpose": "Show backend API surface.",
    },
    {
        "file_name": "03-react-console.png",
        "target": "http://127.0.0.1:5173",
        "purpose": "Show frontend console and API base.",
    },
    {
        "file_name": "04-async-indexing.png",
        "target": "React upload panel",
        "purpose": "Show task_id, status polling, and chunk_count.",
    },
    {
        "file_name": "05-document-search.png",
        "target": "React search panel",
        "purpose": "Show top_k chunks, distance, and source.",
    },
    {
        "file_name": "06-agent-tools-steps.png",
        "target": "React agent panel",
        "purpose": "Show intent, answer, and Agent steps.",
    },
    {
        "file_name": "07-memory-update.png",
        "target": "React agent panel",
        "purpose": "Show explicit memory update and memory_used.",
    },
    {
        "file_name": "08-demo-smoke-report.png",
        "target": "data/demo/runs latest Markdown report",
        "purpose": "Show deterministic demo smoke passed.",
    },
]

RECORDING_FLOW = [
    {"time": "0-10s", "screen": "README", "talk_track": "Project goal and stack."},
    {"time": "10-20s", "screen": "FastAPI Docs", "talk_track": "Core API routes."},
    {"time": "20-35s", "screen": "React upload", "talk_track": "Async indexing task flow."},
    {"time": "35-50s", "screen": "Search panel", "talk_track": "Redis vector retrieval results."},
    {"time": "50-70s", "screen": "Agent panel", "talk_track": "Tool calls and observable steps."},
    {"time": "70-80s", "screen": "Memory request", "talk_track": "Explicit memory update."},
    {"time": "80-90s", "screen": "Smoke report", "talk_track": "Deterministic verification report."},
]

RECORDING_ASSETS = [
    {
        "file_name": "90-second-demo.mp4",
        "purpose": "Final portfolio recording that follows the 90-second flow.",
    }
]

DEMO_COMMANDS = [
    {
        "name": "Backend health",
        "command": 'Invoke-RestMethod -Uri "http://127.0.0.1:8025/api/v1/health"',
    },
    {
        "name": "Redis health",
        "command": 'Invoke-RestMethod -Uri "http://127.0.0.1:8025/api/v1/health/redis"',
    },
    {
        "name": "Frontend health",
        "command": 'Invoke-WebRequest -Uri "http://127.0.0.1:5173" | Select-Object StatusCode',
    },
    {
        "name": "Demo smoke",
        "command": r".\.venv\Scripts\python.exe scripts\demo_smoke.py",
    },
    {
        "name": "Retrieval eval",
        "command": r".\.venv\Scripts\python.exe scripts\evaluate_retrieval.py --top-k 3",
    },
]

HONEST_BOUNDARIES = [
    "Repository defaults keep deterministic fake embedding for no-key local demos; real semantic claims require an EMBEDDING_API_KEY, a rebuilt Redis index, and a fresh retrieval eval report.",
    "Retrieval eval and answer eval measure different things; cite the specific report and metric instead of saying quality is universally solved.",
    "DOCX and PDF are supported. PDF text-layer extraction works with PyMuPDF; scanned-page OCR is optional and depends on PaddleOCR or a configured vision LLM API.",
    "RQ worker is a first version without retry backoff, dead-letter queue, dashboard, or scheduler.",
    "Local-file checkpoint supports demo persistence but not production Redis/Postgres resume.",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a portfolio/demo package from existing reports and docs."
    )
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--assets-dir", type=Path, default=DEFAULT_ASSETS_DIR)
    return parser.parse_args()


def find_latest_file(directory: Path, pattern: str) -> Path | None:
    candidates = [path for path in directory.glob(pattern) if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def read_json_file(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}.")
    return data


def relative_path(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def report_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    if report is None:
        return {"available": False}
    summary = report.get("summary", {})
    if not isinstance(summary, dict):
        return {"available": True}
    return {"available": True, **summary}


def resolve_under_root(root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return root / path


def build_asset_manifest(
    project_root: Path, assets_dir: Path = DEFAULT_ASSETS_DIR
) -> dict[str, Any]:
    root = project_root.resolve()
    resolved_assets_dir = resolve_under_root(root, assets_dir)
    screenshots = []
    missing_files = []
    for item in SCREENSHOT_CHECKLIST:
        path = resolved_assets_dir / item["file_name"]
        exists = path.is_file()
        if not exists:
            missing_files.append(item["file_name"])
        screenshots.append(
            {
                **item,
                "path": relative_path(path, root),
                "exists": exists,
            }
        )

    recordings = []
    for item in RECORDING_ASSETS:
        path = resolved_assets_dir / item["file_name"]
        exists = path.is_file()
        if not exists:
            missing_files.append(item["file_name"])
        recordings.append(
            {
                **item,
                "path": relative_path(path, root),
                "exists": exists,
            }
        )

    return {
        "assets_dir": relative_path(resolved_assets_dir, root),
        "portfolio_assets_ready": len(missing_files) == 0,
        "missing_count": len(missing_files),
        "missing_files": missing_files,
        "required_screenshots": screenshots,
        "required_recordings": recordings,
    }


def build_demo_package(
    project_root: Path, assets_dir: Path = DEFAULT_ASSETS_DIR
) -> dict[str, Any]:
    root = project_root.resolve()
    demo_runs_dir = root / "data" / "demo" / "runs"
    eval_runs_dir = root / "data" / "eval" / "runs"

    latest_smoke_json = find_latest_file(demo_runs_dir, "demo_smoke_*.json")
    latest_smoke_md = find_latest_file(demo_runs_dir, "demo_smoke_*.md")
    latest_eval_json = find_latest_file(eval_runs_dir, "retrieval_eval_*.json")
    latest_eval_md = find_latest_file(eval_runs_dir, "retrieval_eval_*.md")

    smoke_report = read_json_file(latest_smoke_json)
    eval_report = read_json_file(latest_eval_json)
    smoke_summary = report_summary(smoke_report)
    eval_summary = report_summary(eval_report)
    smoke_passed = bool(
        smoke_summary.get("available")
        and smoke_summary.get("failed") == 0
        and smoke_summary.get("passed", 0) > 0
    )
    asset_manifest = build_asset_manifest(root, assets_dir)

    return {
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "project": "AI Resume Job Agent",
            "recording_ready": smoke_passed,
            "portfolio_assets_ready": asset_manifest["portfolio_assets_ready"],
            "project_root": ".",
        },
        "latest_reports": {
            "demo_smoke_json": relative_path(latest_smoke_json, root),
            "demo_smoke_markdown": relative_path(latest_smoke_md, root),
            "retrieval_eval_json": relative_path(latest_eval_json, root),
            "retrieval_eval_markdown": relative_path(latest_eval_md, root),
            "demo_smoke_summary": smoke_summary,
            "retrieval_eval_summary": eval_summary,
        },
        "screenshot_checklist": SCREENSHOT_CHECKLIST,
        "asset_manifest": asset_manifest,
        "recording_flow": RECORDING_FLOW,
        "demo_commands": DEMO_COMMANDS,
        "honest_boundaries": HONEST_BOUNDARIES,
        "next_manual_actions": [
            "Run scripts/demo_smoke.py before recording.",
            "Save the eight screenshots listed in screenshot_checklist to data/demo/assets/.",
            "Record the 90-second flow as data/demo/assets/90-second-demo.mp4.",
            "Keep the latest generated package with the final portfolio material.",
        ],
    }


def write_json_package(package: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(package, ensure_ascii=False, indent=2), encoding="utf-8")


def write_markdown_package(package: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Demo Package",
        "",
        f"- generated_at: `{package['summary']['generated_at']}`",
        f"- project: `{package['summary']['project']}`",
        f"- recording_ready: `{package['summary']['recording_ready']}`",
        f"- portfolio_assets_ready: `{package['summary']['portfolio_assets_ready']}`",
        "",
        "## Latest Reports",
        "",
    ]
    reports = package["latest_reports"]
    lines.extend(
        [
            f"- demo_smoke_json: `{reports.get('demo_smoke_json') or 'missing'}`",
            f"- demo_smoke_markdown: `{reports.get('demo_smoke_markdown') or 'missing'}`",
            f"- retrieval_eval_json: `{reports.get('retrieval_eval_json') or 'missing'}`",
            f"- retrieval_eval_markdown: `{reports.get('retrieval_eval_markdown') or 'missing'}`",
            "",
            "## Screenshot Checklist",
            "",
            "| file | target | purpose |",
            "|---|---|---|",
        ]
    )
    for item in package["screenshot_checklist"]:
        lines.append(f"| {item['file_name']} | {item['target']} | {item['purpose']} |")
    asset_manifest = package["asset_manifest"]
    lines.extend(
        [
            "",
            "## Asset Status",
            "",
            f"- assets_dir: `{asset_manifest['assets_dir']}`",
            f"- portfolio_assets_ready: `{asset_manifest['portfolio_assets_ready']}`",
            f"- missing_count: `{asset_manifest['missing_count']}`",
            "",
            "| status | file | path | purpose |",
            "|---|---|---|---|",
        ]
    )
    for item in asset_manifest["required_screenshots"]:
        status = "done" if item["exists"] else "missing"
        lines.append(f"| {status} | {item['file_name']} | {item['path']} | {item['purpose']} |")
    for item in asset_manifest["required_recordings"]:
        status = "done" if item["exists"] else "missing"
        lines.append(f"| {status} | {item['file_name']} | {item['path']} | {item['purpose']} |")
    lines.extend(["", "## 90-Second Recording Flow", "", "| time | screen | talk track |", "|---|---|---|"])
    for item in package["recording_flow"]:
        lines.append(f"| {item['time']} | {item['screen']} | {item['talk_track']} |")
    lines.extend(["", "## Demo Commands", ""])
    for item in package["demo_commands"]:
        lines.extend([f"### {item['name']}", "", "```powershell", item["command"], "```", ""])
    lines.extend(["## Honest Boundaries", ""])
    for boundary in package["honest_boundaries"]:
        lines.append(f"- {boundary}")
    lines.extend(["", "## Next Manual Actions", ""])
    for action in package["next_manual_actions"]:
        lines.append(f"- {action}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    package = build_demo_package(args.project_root, args.assets_dir)
    json_path = args.output_dir / f"demo_package_{timestamp}.json"
    markdown_path = args.output_dir / f"demo_package_{timestamp}.md"
    write_json_package(package, json_path)
    write_markdown_package(package, markdown_path)
    print(f"recording_ready={package['summary']['recording_ready']}")
    print(f"portfolio_assets_ready={package['summary']['portfolio_assets_ready']}")
    print(f"json_package={json_path}")
    print(f"markdown_package={markdown_path}")


if __name__ == "__main__":
    main()
