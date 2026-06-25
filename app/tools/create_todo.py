import re
from dataclasses import dataclass


class TodoCreationError(ValueError):
    """Raised when todo items cannot be extracted from user input."""


@dataclass(frozen=True)
class TodoItem:
    title: str
    done: bool = False


@dataclass(frozen=True)
class TodoList:
    items: list[TodoItem]

    def to_markdown(self) -> str:
        lines = ["待办清单："]
        lines.extend(f"- [ ] {item.title}" for item in self.items)
        return "\n".join(lines)


_TODO_KEYWORDS = (
    "待办",
    "todo",
    "TODO",
    "任务清单",
    "事项清单",
)

_TODO_PREFIXES = (
    "请帮我生成",
    "请帮我创建",
    "请帮我列",
    "帮我生成",
    "帮我创建",
    "帮我列",
    "生成",
    "创建",
    "列",
)

_TODO_SUFFIXES = (
    "生成待办",
    "生成待办清单",
    "创建待办",
    "创建待办清单",
    "列成待办",
    "列成待办清单",
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


def extract_todo_text(text: str) -> str | None:
    if not _contains_todo_keyword(text):
        return None
    candidate = _normalize_text(text)
    if ":" in candidate:
        left, right = candidate.split(":", 1)
        if _contains_todo_keyword(left):
            candidate = right
    else:
        candidate = _remove_todo_words(candidate)
    candidate = _remove_edge_phrases(candidate)
    return candidate


def create_todo(text: str) -> TodoList:
    extracted = extract_todo_text(text)
    candidate = extracted if extracted is not None else _normalize_text(text)
    if extracted is None and _contains_todo_keyword(text):
        candidate = ""
    items = [_clean_item(item) for item in _split_items(candidate)]
    items = [item for item in items if item]
    if not items:
        raise TodoCreationError("No todo items were found.")
    if len(items) > 20:
        raise TodoCreationError("Too many todo items.")
    return TodoList(items=[TodoItem(title=item) for item in items])


def _contains_todo_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in _TODO_KEYWORDS)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.translate(_FULL_WIDTH_PUNCTUATION)).strip()


def _remove_todo_words(text: str) -> str:
    candidate = text
    for prefix in _TODO_PREFIXES:
        if candidate.startswith(prefix):
            candidate = candidate.removeprefix(prefix)
            break
    for keyword in _TODO_KEYWORDS:
        candidate = re.sub(re.escape(keyword), "", candidate, flags=re.IGNORECASE)
    return candidate


def _remove_edge_phrases(text: str) -> str:
    candidate = text.strip(" :,.!?")
    for suffix in _TODO_SUFFIXES:
        if candidate.endswith(suffix):
            candidate = candidate.removesuffix(suffix)
            break
    return candidate.strip(" :,.!?")


def _split_items(text: str) -> list[str]:
    text = re.sub(r"\b(然后|以及|还有|并且)\b", ",", text)
    text = re.sub(r"\s+(和|与)\s+", ",", text)
    return re.split(r"[,;\n]+", text)


def _clean_item(text: str) -> str:
    item = text.strip()
    item = re.sub(r"^[-*]\s*", "", item)
    item = re.sub(r"^\d+[.)、]\s*", "", item)
    return item.strip(" :,.!?")
