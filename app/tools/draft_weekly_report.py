import re
from dataclasses import dataclass, field


class WeeklyReportDraftError(ValueError):
    """Raised when weekly report content cannot be extracted."""


@dataclass(frozen=True)
class WeeklyReportDraft:
    completed: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = ["周报草稿：", "", "## 本周完成"]
        lines.extend(_format_items(self.completed, "待补充本周完成事项。"))
        lines.extend(["", "## 遇到的问题"])
        lines.extend(_format_items(self.blockers, "暂无明确阻塞事项。"))
        lines.extend(["", "## 下周计划"])
        lines.extend(_format_items(self.next_steps, "待补充下周计划。"))
        if self.notes:
            lines.extend(["", "## 备注"])
            lines.extend(f"- {item}" for item in self.notes)
        return "\n".join(lines)


_WEEKLY_REPORT_KEYWORDS = (
    "周报",
    "工作周报",
    "weekly report",
)

_WEEKLY_REPORT_ACTIONS = (
    "写",
    "生成",
    "整理",
    "草稿",
    "输出",
    "draft",
)

_WEEKLY_REPORT_PREFIXES = (
    "请帮我写周报",
    "请帮我生成周报",
    "请帮我整理周报",
    "帮我写周报",
    "帮我生成周报",
    "帮我整理周报",
    "写周报",
    "生成周报",
    "整理周报",
    "周报草稿",
)

_SECTION_LABELS: dict[str, str] = {
    "本周完成": "completed",
    "本周工作": "completed",
    "已完成": "completed",
    "完成": "completed",
    "进展": "completed",
    "遇到的问题": "blockers",
    "问题": "blockers",
    "困难": "blockers",
    "阻塞": "blockers",
    "风险": "blockers",
    "下周计划": "next_steps",
    "后续计划": "next_steps",
    "下一步": "next_steps",
    "下周": "next_steps",
    "计划": "next_steps",
    "备注": "notes",
    "补充": "notes",
}

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


def extract_weekly_report_text(text: str) -> str | None:
    if not _contains_weekly_report_intent(text):
        return None
    candidate = _normalize_text(text)
    if ":" in candidate:
        left, right = candidate.split(":", 1)
        if _contains_weekly_report_keyword(left):
            candidate = right
    else:
        for prefix in _WEEKLY_REPORT_PREFIXES:
            if candidate.startswith(prefix):
                candidate = candidate.removeprefix(prefix)
                break
    return candidate.strip(" :,.!?")


def draft_weekly_report(text: str) -> WeeklyReportDraft:
    extracted = extract_weekly_report_text(text)
    candidate = extracted if extracted is not None else _normalize_text(text)
    if not candidate:
        raise WeeklyReportDraftError("No weekly report content was found.")

    sections = _parse_sections(candidate)
    if not any(sections.values()):
        raise WeeklyReportDraftError("No weekly report content was found.")
    total_items = sum(len(items) for items in sections.values())
    if total_items > 40:
        raise WeeklyReportDraftError("Too many weekly report items.")
    return WeeklyReportDraft(
        completed=sections["completed"],
        blockers=sections["blockers"],
        next_steps=sections["next_steps"],
        notes=sections["notes"],
    )


def _contains_weekly_report_intent(text: str) -> bool:
    lowered = text.lower()
    return _contains_weekly_report_keyword(lowered) and any(
        action in lowered for action in _WEEKLY_REPORT_ACTIONS
    )


def _contains_weekly_report_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in _WEEKLY_REPORT_KEYWORDS)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_FULL_WIDTH_PUNCTUATION)).strip()


def _parse_sections(text: str) -> dict[str, list[str]]:
    sections = {"completed": [], "blockers": [], "next_steps": [], "notes": []}
    label_regex = "|".join(
        re.escape(label)
        for label in sorted(_SECTION_LABELS, key=len, reverse=True)
    )
    parts = re.split(rf"({label_regex})\s*:", text)
    if len(parts) == 1:
        sections["completed"] = _split_items(text)
        return sections

    leading = parts[0].strip(" ;,.")
    if leading:
        sections["completed"].extend(_split_items(leading))

    for index in range(1, len(parts), 2):
        label = parts[index]
        value = parts[index + 1] if index + 1 < len(parts) else ""
        section = _SECTION_LABELS[label]
        sections[section].extend(_split_items(value))
    return sections


def _split_items(text: str) -> list[str]:
    normalized = re.sub(r"(然后|以及|还有|并且)", ",", text)
    normalized = re.sub(r"\s+(和|与)\s+", ",", normalized)
    items = [_clean_item(item) for item in re.split(r"[,;\n]+", normalized)]
    return [item for item in items if item]


def _clean_item(text: str) -> str:
    item = text.strip()
    item = re.sub(r"^[-*]\s*", "", item)
    item = re.sub(r"^\d+[.)、]\s*", "", item)
    return item.strip(" :,.!?")


def _format_items(items: list[str], fallback: str) -> list[str]:
    if not items:
        return [f"- {fallback}"]
    return [f"- {item}" for item in items]
