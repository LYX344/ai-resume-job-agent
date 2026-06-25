import pytest

from app.tools.create_todo import TodoCreationError, create_todo, extract_todo_text


def test_extract_todo_text_from_chinese_query() -> None:
    text = extract_todo_text("帮我生成待办：复习 Redis、写简历、提交周报")

    assert text == "复习 Redis,写简历,提交周报"


def test_create_todo_returns_markdown_checklist() -> None:
    todo_list = create_todo("帮我生成待办：复习 Redis、写简历、提交周报")

    assert [item.title for item in todo_list.items] == [
        "复习 Redis",
        "写简历",
        "提交周报",
    ]
    assert todo_list.to_markdown() == (
        "待办清单：\n"
        "- [ ] 复习 Redis\n"
        "- [ ] 写简历\n"
        "- [ ] 提交周报"
    )


def test_create_todo_rejects_empty_items() -> None:
    with pytest.raises(TodoCreationError):
        create_todo("待办：")
