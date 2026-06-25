import pytest

from app.tools.draft_weekly_report import (
    WeeklyReportDraftError,
    draft_weekly_report,
    extract_weekly_report_text,
)


def test_extract_weekly_report_text_from_chinese_query() -> None:
    text = extract_weekly_report_text(
        "帮我写周报：本周完成：接入 Redis、补充测试；问题：没有 API Key；下周计划：实现前端"
    )

    assert text == "本周完成:接入 Redis,补充测试;问题:没有 API Key;下周计划:实现前端"


def test_draft_weekly_report_returns_markdown_sections() -> None:
    draft = draft_weekly_report(
        "帮我写周报：本周完成：接入 Redis、补充测试；"
        "问题：没有 API Key；下周计划：实现前端、完善 README"
    )

    assert draft.completed == ["接入 Redis", "补充测试"]
    assert draft.blockers == ["没有 API Key"]
    assert draft.next_steps == ["实现前端", "完善 README"]
    assert draft.to_markdown() == (
        "周报草稿：\n"
        "\n"
        "## 本周完成\n"
        "- 接入 Redis\n"
        "- 补充测试\n"
        "\n"
        "## 遇到的问题\n"
        "- 没有 API Key\n"
        "\n"
        "## 下周计划\n"
        "- 实现前端\n"
        "- 完善 README"
    )


def test_draft_weekly_report_rejects_empty_content() -> None:
    with pytest.raises(WeeklyReportDraftError):
        draft_weekly_report("帮我写周报：")
