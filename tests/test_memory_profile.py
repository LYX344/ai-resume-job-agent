from app.memory.profile import (
    extract_memory_updates,
    format_memory_context,
    merge_memory_profile,
)
from app.models.memory import MemoryProfile


def test_extract_memory_updates_from_explicit_preference() -> None:
    updates = extract_memory_updates("请记住：我喜欢先给结论、回答尽量简洁")

    assert updates["preferences"] == ["我喜欢先给结论", "回答尽量简洁"]
    assert updates["project_context"] == []
    assert updates["constraints"] == []


def test_extract_memory_updates_classifies_project_context_and_constraints() -> None:
    updates = extract_memory_updates("记住：我的项目是 Agent RAG 助手、不要泄露 API Key")

    assert updates["project_context"] == ["我的项目是 Agent RAG 助手"]
    assert updates["constraints"] == ["不要泄露 API Key"]


def test_merge_memory_profile_deduplicates_items() -> None:
    profile = MemoryProfile(preferences=["回答尽量简洁"])

    updated = merge_memory_profile(
        profile,
        {
            "preferences": ["回答尽量简洁", "先给结论"],
            "project_context": [],
            "constraints": [],
        },
    )

    assert updated.preferences == ["回答尽量简洁", "先给结论"]
    assert updated.updated_at is not None


def test_format_memory_context_returns_readable_sections() -> None:
    profile = MemoryProfile(
        preferences=["回答尽量简洁"],
        project_context=["项目使用 FastAPI 和 Redis"],
        constraints=["不要泄露 API Key"],
    )

    context = format_memory_context(profile)

    assert "用户偏好：" in context
    assert "- 回答尽量简洁" in context
    assert "项目背景：" in context
    assert "常用约束：" in context
