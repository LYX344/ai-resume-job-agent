import re
from datetime import datetime, timezone

from app.models.memory import MemoryProfile


MAX_MEMORY_ITEMS_PER_SECTION = 20

_MEMORY_TRIGGERS = (
    "记住",
    "请记住",
    "以后",
    "我喜欢",
    "我希望",
    "我的偏好",
    "默认",
    "要求",
)

_FULL_WIDTH_PUNCTUATION = str.maketrans(
    {
        "：": ":",
        "，": ",",
        "；": ";",
        "。": ".",
        "、": ",",
        "？": "?",
        "！": "!",
    }
)


def extract_memory_updates(text: str) -> dict[str, list[str]]:
    normalized = _normalize_text(text)
    if not _has_memory_trigger(normalized):
        return _empty_updates()

    candidate = _remove_memory_prefix(normalized)
    items = [_clean_item(item) for item in re.split(r"[,;\n]+", candidate)]
    items = [item for item in items if item]
    updates = _empty_updates()
    for item in items:
        updates[_classify_memory_item(item)].append(item)
    return updates


def merge_memory_profile(
    profile: MemoryProfile,
    updates: dict[str, list[str]],
) -> MemoryProfile:
    if not any(updates.values()):
        return profile
    return MemoryProfile(
        profile_id=profile.profile_id,
        preferences=_merge_items(profile.preferences, updates["preferences"]),
        project_context=_merge_items(profile.project_context, updates["project_context"]),
        constraints=_merge_items(profile.constraints, updates["constraints"]),
        updated_at=datetime.now(timezone.utc).isoformat(),
    )


def format_memory_context(profile: MemoryProfile | None) -> str:
    if profile is None or profile.item_count == 0:
        return ""

    sections: list[str] = []
    if profile.preferences:
        sections.append("用户偏好：\n" + _format_items(profile.preferences))
    if profile.project_context:
        sections.append("项目背景：\n" + _format_items(profile.project_context))
    if profile.constraints:
        sections.append("常用约束：\n" + _format_items(profile.constraints))
    return "\n\n".join(sections)


def format_memory_updates(updates: dict[str, list[str]]) -> str:
    if not any(updates.values()):
        return "没有识别到可保存的长期记忆。"

    lines = ["已记录长期记忆："]
    if updates["preferences"]:
        lines.append("- 用户偏好：")
        lines.extend(f"  - {item}" for item in updates["preferences"])
    if updates["project_context"]:
        lines.append("- 项目背景：")
        lines.extend(f"  - {item}" for item in updates["project_context"])
    if updates["constraints"]:
        lines.append("- 常用约束：")
        lines.extend(f"  - {item}" for item in updates["constraints"])
    return "\n".join(lines)


def _empty_updates() -> dict[str, list[str]]:
    return {"preferences": [], "project_context": [], "constraints": []}


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_FULL_WIDTH_PUNCTUATION)).strip()


def _has_memory_trigger(text: str) -> bool:
    lowered = text.lower()
    return any(trigger.lower() in lowered for trigger in _MEMORY_TRIGGERS)


def _remove_memory_prefix(text: str) -> str:
    candidate = text.strip()
    if ":" in candidate:
        left, right = candidate.split(":", 1)
        if _has_memory_trigger(left):
            candidate = right
    for prefix in ("请记住", "记住", "以后请", "以后", "我的偏好是"):
        if candidate.startswith(prefix):
            candidate = candidate.removeprefix(prefix)
            break
    return candidate.strip(" :,.!?")


def _classify_memory_item(item: str) -> str:
    if re.search(r"(不要|不能|必须|要求|只允许|禁止|隐私|安全|密钥|key)", item, flags=re.IGNORECASE):
        return "constraints"
    if re.search(r"(项目|技术栈|简历|实习|作品集|agent|rag|redis|fastapi|python)", item, flags=re.IGNORECASE):
        return "project_context"
    return "preferences"


def _clean_item(text: str) -> str:
    item = text.strip()
    item = re.sub(r"^[-*]\s*", "", item)
    item = re.sub(r"^\d+[.)、]\s*", "", item)
    return item.strip(" :,.!?")


def _merge_items(existing: list[str], new_items: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for item in [*existing, *new_items]:
        normalized = item.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        merged.append(item)
    return merged[-MAX_MEMORY_ITEMS_PER_SECTION:]


def _format_items(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)
