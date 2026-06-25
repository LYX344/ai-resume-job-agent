"""Build a text-layer PDF from a resume Markdown file (for resume RAG eval).

The resume PDF is a real-world sample for the resume-assistant Agent: parse the
resume PDF -> index -> RAG can answer questions about skills / projects /
education, which is the foundation for JD matching and application drafting.

This produces a *digital* (text-layer) PDF, matching how real resumes are
exported from Word/WPS. Replace the output with a true Word-exported PDF later
and the rest of the pipeline is unchanged.

Usage:
    python scripts/build_resume_pdf.py \
        --source ../resume/your_resume.md \
        --output data/uploads/resume_sample.pdf
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pymupdf

from app.rag.document_loader import load_document


def _clean_markdown(md: str) -> list[str]:
    lines: list[str] = []
    for raw in md.splitlines():
        line = raw.rstrip()
        line = re.sub(r"^#{1,6}\s*", "", line)
        line = line.replace("**", "")
        line = re.sub(r"^\s*-\s+", "· ", line)
        lines.append(line)
    return lines


def build_pdf(lines: list[str], out_path: Path) -> int:
    document = pymupdf.open()
    rect = pymupdf.paper_rect("a4")
    margin = 50.0
    fontsize = 11

    page_bottom = rect.height - margin
    page = document.new_page(width=rect.width, height=rect.height)
    cursor_y = margin
    for line in lines:
        if not line.strip():
            cursor_y += fontsize * 0.7
            continue
        if cursor_y > page_bottom - fontsize * 1.5:
            page = document.new_page(width=rect.width, height=rect.height)
            cursor_y = margin
        box = pymupdf.Rect(margin, cursor_y, rect.width - margin, page_bottom)
        remaining = page.insert_textbox(box, line, fontsize=fontsize, fontname="china-s")
        if remaining < 0:
            page = document.new_page(width=rect.width, height=rect.height)
            cursor_y = margin
            box = pymupdf.Rect(margin, cursor_y, rect.width - margin, page_bottom)
            remaining = page.insert_textbox(box, line, fontsize=fontsize, fontname="china-s")
        used = box.height - remaining
        cursor_y += used + 4

    out_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(out_path)
    page_count = document.page_count
    document.close()
    return page_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a text-layer resume PDF from Markdown.")
    parser.add_argument(
        "--source",
        type=Path,
        default=PROJECT_ROOT.parent / "resume" / "your_resume.md",
        help="Resume Markdown source file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/uploads/resume_sample.pdf"),
        help="Output PDF path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.source.exists():
        print(f"source not found: {args.source}")
        return 1

    md = args.source.read_text(encoding="utf-8")
    lines = _clean_markdown(md)
    page_count = build_pdf(lines, args.output)
    print(f"pdf_pages: {page_count}")
    print(f"pdf_path: {args.output}")

    loaded = load_document(args.output)
    print(f"extracted_chars: {len(loaded.content)}")
    verify_path = args.output.with_name("resume_sample_extracted.txt")
    verify_path.write_text(loaded.content, encoding="utf-8")
    print(f"extracted_text_utf8: {verify_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
