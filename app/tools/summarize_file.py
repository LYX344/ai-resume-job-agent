import re
from dataclasses import dataclass, field
from pathlib import Path


class FileSummaryError(ValueError):
    """Raised when a file cannot be safely summarized."""


@dataclass(frozen=True)
class FileSummary:
    file_path: str
    title: str
    line_count: int
    char_count: int
    headings: list[str] = field(default_factory=list)
    highlights: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"文件摘要：{self.file_path}",
            f"- 标题：{self.title}",
            f"- 行数：{self.line_count}",
            f"- 字符数：{self.char_count}",
        ]
        if self.headings:
            lines.append("- 主要标题：")
            lines.extend(f"  - {heading}" for heading in self.headings)
        if self.highlights:
            lines.append("- 内容要点：")
            lines.extend(f"  - {highlight}" for highlight in self.highlights)
        return "\n".join(lines)


_SUMMARY_KEYWORDS = (
    "总结",
    "摘要",
    "概括",
    "summarize",
    "summary",
)

_ALLOWED_ROOT_PREFIXES = ("docs", "data/uploads")
_ALLOWED_ROOT_FILES = {"README.md"}
_SUPPORTED_SUFFIXES = {".md", ".txt"}
_MAX_FILE_CHARS = 50_000


def extract_summary_file_path(text: str) -> str | None:
    if not _contains_summary_keyword(text):
        return None
    match = re.search(r"([\w./\\-]+\.(?:md|txt))", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).replace("\\", "/").strip("'\"")


def summarize_file(file_path: str, *, project_root: Path | None = None) -> FileSummary:
    root = (project_root or Path.cwd()).resolve()
    target = _resolve_safe_path(file_path, root)
    content = target.read_text(encoding="utf-8")
    if len(content) > _MAX_FILE_CHARS:
        raise FileSummaryError("File is too large to summarize locally.")
    if not content.strip():
        raise FileSummaryError("File is empty.")

    lines = content.splitlines()
    headings = _extract_headings(lines)
    highlights = _extract_highlights(lines)
    return FileSummary(
        file_path=target.relative_to(root).as_posix(),
        title=headings[0] if headings else target.name,
        line_count=len(lines),
        char_count=len(content),
        headings=headings[:5],
        highlights=highlights[:5],
    )


def _contains_summary_keyword(text: str) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in _SUMMARY_KEYWORDS)


def _resolve_safe_path(file_path: str, root: Path) -> Path:
    if not file_path:
        raise FileSummaryError("No file path was found.")
    candidate = file_path.replace("\\", "/").strip("'\" ")
    path = Path(candidate)
    if path.is_absolute() or ".." in path.parts:
        raise FileSummaryError("Only safe relative file paths are supported.")
    if path.suffix.lower() not in _SUPPORTED_SUFFIXES:
        raise FileSummaryError("Only .md and .txt files can be summarized.")

    normalized = path.as_posix()
    first_part = path.parts[0] if path.parts else ""
    first_two_parts = "/".join(path.parts[:2])
    in_allowed_dir = first_part == "docs" or first_two_parts in _ALLOWED_ROOT_PREFIXES
    if normalized not in _ALLOWED_ROOT_FILES and not in_allowed_dir:
        raise FileSummaryError("File path is outside the allowed summary roots.")

    target = (root / path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise FileSummaryError("File path is outside the project root.") from exc
    if not target.exists() or not target.is_file():
        raise FileSummaryError("File does not exist.")
    return target


def _extract_headings(lines: list[str]) -> list[str]:
    headings: list[str] = []
    for line in lines:
        match = re.match(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", line)
        if match:
            headings.append(_clean_text(match.group(1)))
    return headings


def _extract_highlights(lines: list[str]) -> list[str]:
    highlights: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(("- ", "* ")):
            highlights.append(_clean_text(stripped[2:]))
            continue
        if len(stripped) >= 18:
            highlights.append(_clean_text(stripped))
        if len(highlights) >= 5:
            break
    return highlights


def _clean_text(text: str) -> str:
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip(" -*\t")
