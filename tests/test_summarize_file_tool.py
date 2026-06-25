from pathlib import Path

import pytest

from app.tools.summarize_file import (
    FileSummaryError,
    extract_summary_file_path,
    summarize_file,
)


def test_extract_summary_file_path_from_query() -> None:
    assert extract_summary_file_path("请总结 docs/notes.md") == "docs/notes.md"


def test_summarize_file_returns_markdown_summary(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    target = docs_dir / "notes.md"
    target.write_text(
        "# 项目笔记\n\n"
        "这是一个用于测试文件总结的文档。\n\n"
        "## Redis\n\n"
        "- Redis 用于缓存和向量检索。\n"
        "- Agent 使用工具节点。\n",
        encoding="utf-8",
    )

    summary = summarize_file("docs/notes.md", project_root=tmp_path)

    assert summary.file_path == "docs/notes.md"
    assert summary.title == "项目笔记"
    assert summary.headings == ["项目笔记", "Redis"]
    assert "Redis 用于缓存和向量检索。" in summary.highlights
    assert "文件摘要：docs/notes.md" in summary.to_markdown()


def test_summarize_file_rejects_unsafe_path(tmp_path: Path) -> None:
    with pytest.raises(FileSummaryError):
        summarize_file("../secret.md", project_root=tmp_path)
