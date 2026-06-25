"""Smoke test: real PaddleOCR on a synthetic scanned PDF (image-only page).

It builds a PDF whose single page is an *image* of mixed Chinese/English text
(no text layer), then runs the real extraction pipeline. This verifies:

- scanned-page detection (no text layer -> OCR route),
- PaddleOCR actually recognising mixed CN/EN text.

First run downloads PaddleOCR models and needs network access.

Usage:
    .venv\\Scripts\\python.exe scripts\\smoke_pdf_ocr.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf

from app.rag.pdf_extractor import extract_pdf_text


def _build_scanned_pdf() -> bytes:
    source = pymupdf.open()
    page = source.new_page()
    page.insert_text((72, 110), "发票 Invoice", fontsize=30, fontname="china-s")
    page.insert_text((72, 170), "金额 Amount 100 元 RMB", fontsize=24, fontname="china-s")
    page.insert_text((72, 230), "知识库 RAG Agent 项目", fontsize=24, fontname="china-s")
    pixmap = page.get_pixmap(dpi=200)
    image_bytes = pixmap.tobytes("png")
    source.close()

    scan = pymupdf.open()
    scan_page = scan.new_page(width=pixmap.width, height=pixmap.height)
    scan_page.insert_image(scan_page.rect, stream=image_bytes)
    data = scan.tobytes()
    scan.close()
    return data


def main() -> int:
    data = _build_scanned_pdf()
    print("scanned_pdf_bytes:", len(data), flush=True)

    result = extract_pdf_text(data)

    print("ocr_provider:", result.ocr_provider)
    print("page_count:", result.page_count)
    print("text_layer_pages:", result.text_layer_page_count)
    print("ocr_pages:", result.ocr_page_count)
    print("ocr_unavailable_pages:", result.ocr_unavailable_page_count)
    print("----- EXTRACTED TEXT BEGIN -----")
    print(result.text)
    print("----- EXTRACTED TEXT END -----")

    output_path = (
        Path(__file__).resolve().parent.parent / "data" / "uploads" / "ocr_smoke_result.txt"
    )
    output_path.write_text(result.text, encoding="utf-8")
    print("written_utf8:", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
