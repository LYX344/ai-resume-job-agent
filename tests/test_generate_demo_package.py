import json
import os
import time
from pathlib import Path

from scripts.generate_demo_package import (
    SCREENSHOT_CHECKLIST,
    build_demo_package,
    find_latest_file,
    write_json_package,
    write_markdown_package,
)


def test_find_latest_file_uses_modified_time_then_name(tmp_path: Path) -> None:
    first = tmp_path / "demo_smoke_20260615_120000.json"
    second = tmp_path / "demo_smoke_20260615_120001.json"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    now = time.time()
    os.utime(first, (now, now))
    os.utime(second, (now + 1, now + 1))

    assert find_latest_file(tmp_path, "demo_smoke_*.json") == second


def test_build_demo_package_reads_latest_reports(tmp_path: Path) -> None:
    demo_dir = tmp_path / "data" / "demo" / "runs"
    eval_dir = tmp_path / "data" / "eval" / "runs"
    demo_dir.mkdir(parents=True)
    eval_dir.mkdir(parents=True)
    (demo_dir / "demo_smoke_20260615_120000.json").write_text(
        json.dumps(
            {
                "summary": {
                    "generated_at": "2026-06-15T12:00:00+00:00",
                    "total": 10,
                    "passed": 10,
                    "failed": 0,
                }
            }
        ),
        encoding="utf-8",
    )
    (demo_dir / "demo_smoke_20260615_120000.md").write_text("# smoke", encoding="utf-8")
    (eval_dir / "retrieval_eval_20260615_120000.json").write_text(
        json.dumps(
            {
                "summary": {
                    "generated_at": "2026-06-15T12:00:00+00:00",
                    "total": 20,
                    "hit_rate": 0.65,
                }
            }
        ),
        encoding="utf-8",
    )

    package = build_demo_package(tmp_path)

    assert package["summary"]["recording_ready"] is True
    assert package["latest_reports"]["demo_smoke_json"].endswith(
        "demo_smoke_20260615_120000.json"
    )
    assert package["latest_reports"]["demo_smoke_summary"]["passed"] == 10
    assert package["latest_reports"]["retrieval_eval_summary"]["hit_rate"] == 0.65
    assert len(package["screenshot_checklist"]) == 8
    assert package["summary"]["portfolio_assets_ready"] is False
    assert package["asset_manifest"]["missing_count"] == 9


def test_build_demo_package_marks_assets_ready_when_files_exist(tmp_path: Path) -> None:
    demo_dir = tmp_path / "data" / "demo" / "runs"
    demo_dir.mkdir(parents=True)
    (demo_dir / "demo_smoke_20260615_120000.json").write_text(
        json.dumps({"summary": {"total": 1, "passed": 1, "failed": 0}}),
        encoding="utf-8",
    )
    assets_dir = tmp_path / "data" / "demo" / "assets"
    assets_dir.mkdir(parents=True)
    for item in SCREENSHOT_CHECKLIST:
        (assets_dir / item["file_name"]).write_bytes(b"fake image")
    (assets_dir / "90-second-demo.mp4").write_bytes(b"fake video")

    package = build_demo_package(tmp_path)

    assert package["summary"]["recording_ready"] is True
    assert package["summary"]["portfolio_assets_ready"] is True
    assert package["asset_manifest"]["missing_count"] == 0


def test_write_demo_package_creates_json_and_markdown(tmp_path: Path) -> None:
    package = {
        "summary": {
            "generated_at": "2026-06-15T12:00:00+00:00",
            "project": "AI Resume Job Agent",
            "recording_ready": True,
            "portfolio_assets_ready": False,
        },
        "latest_reports": {
            "demo_smoke_json": "data/demo/runs/demo.json",
            "demo_smoke_markdown": "data/demo/runs/demo.md",
            "retrieval_eval_json": "data/eval/runs/eval.json",
            "retrieval_eval_markdown": "data/eval/runs/eval.md",
        },
        "screenshot_checklist": [
            {
                "file_name": "01-readme-overview.png",
                "target": "README.md",
                "purpose": "Show overview.",
            }
        ],
        "asset_manifest": {
            "assets_dir": "data/demo/assets",
            "portfolio_assets_ready": False,
            "missing_count": 1,
            "missing_files": ["01-readme-overview.png"],
            "required_screenshots": [
                {
                    "file_name": "01-readme-overview.png",
                    "path": "data/demo/assets/01-readme-overview.png",
                    "purpose": "Show overview.",
                    "exists": False,
                }
            ],
            "required_recordings": [],
        },
        "recording_flow": [
            {"time": "0-10s", "screen": "README", "talk_track": "Project goal."}
        ],
        "demo_commands": [{"name": "Smoke", "command": "python scripts/demo_smoke.py"}],
        "honest_boundaries": ["Fake embedding is not real semantic quality."],
        "next_manual_actions": ["Capture screenshots."],
    }
    json_path = tmp_path / "package.json"
    markdown_path = tmp_path / "package.md"

    write_json_package(package, json_path)
    write_markdown_package(package, markdown_path)

    assert json.loads(json_path.read_text(encoding="utf-8"))["summary"][
        "recording_ready"
    ]
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Demo Package" in markdown
    assert "01-readme-overview.png" in markdown
    assert "portfolio_assets_ready" in markdown
    assert "Fake embedding" in markdown
