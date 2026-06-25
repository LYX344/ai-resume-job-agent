"""PDF extraction pipeline with hybrid text-layer / OCR routing.

Strategy (2026 best practice for RAG):

1. Open the PDF with PyMuPDF.
2. For each page, read the embedded text layer.
   - If the page has enough real text -> it is a digital page, keep the text
     directly (fast, exact, free; stamps/seals and mixed CN/EN do not matter
     because the characters live in the text layer).
   - If the page has (almost) no text -> it is a scanned/image page, render it
     to a PNG and send it to the OCR provider (PaddleOCR or vision LLM), which
     handles mixed Chinese/English and best-effort seal (公章) text.
3. If OCR is unavailable (disabled or not installed), the page degrades to a
   clear placeholder instead of crashing the whole upload.

This routing avoids running expensive OCR on digital pages, prevents OCR noise
from polluting embeddings, and keeps the upload robust.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import Settings
from app.core.config import settings as default_settings
from app.services.ocr_client import OcrError, OcrProvider, get_ocr_provider


class PdfExtractionError(ValueError):
    """Raised when a PDF cannot be opened or parsed at all."""


@dataclass(frozen=True)
class PdfPageExtraction:
    page_number: int
    method: str  # "text_layer" | "ocr" | "ocr_unavailable"
    char_count: int
    text: str


@dataclass
class PdfExtractionResult:
    text: str
    page_count: int
    pages: list[PdfPageExtraction] = field(default_factory=list)
    text_layer_page_count: int = 0
    ocr_page_count: int = 0
    ocr_unavailable_page_count: int = 0
    ocr_provider: str = "none"
    truncated: bool = False


def extract_pdf_text(
    data: bytes,
    *,
    settings: Settings | None = None,
    ocr_provider: OcrProvider | None = None,
) -> PdfExtractionResult:
    """Extract text from PDF bytes using hybrid text-layer / OCR routing.

    ``ocr_provider`` can be injected for testing; otherwise it is built lazily
    from settings only when a scanned page is actually encountered.
    """
    settings = settings or default_settings
    pymupdf = _import_pymupdf()

    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PdfExtractionError(f"Document is not a valid .pdf file: {exc}") from exc

    min_chars = settings.pdf_text_layer_min_chars
    dpi = settings.pdf_ocr_dpi
    max_pages = settings.pdf_ocr_max_pages

    pages: list[PdfPageExtraction] = []
    resolved_provider = ocr_provider
    truncated = False

    try:
        total_pages = document.page_count
        for page_index in range(total_pages):
            page_number = page_index + 1
            if page_number > max_pages:
                truncated = True
                break

            page = document.load_page(page_index)
            text_layer = page.get_text("text").strip()

            if len(text_layer) >= min_chars:
                pages.append(
                    PdfPageExtraction(
                        page_number=page_number,
                        method="text_layer",
                        char_count=len(text_layer),
                        text=text_layer,
                    )
                )
                continue

            if resolved_provider is None:
                resolved_provider = get_ocr_provider(settings)

            image_bytes = _render_page_png(page, dpi)
            try:
                ocr_result = resolved_provider.ocr_image(image_bytes)
            except OcrError as exc:
                placeholder = (
                    f"[第 {page_number} 页为扫描件/图片，未能提取文字："
                    f"{_short_reason(exc)}]"
                )
                pages.append(
                    PdfPageExtraction(
                        page_number=page_number,
                        method="ocr_unavailable",
                        char_count=0,
                        text=placeholder,
                    )
                )
                continue

            ocr_text = ocr_result.text.strip()
            seal_suffix = _format_seal_texts(ocr_result.seal_texts)
            merged_text = (ocr_text + seal_suffix).strip()
            if not merged_text:
                merged_text = f"[第 {page_number} 页为扫描件/图片，OCR 未识别到文字]"
            pages.append(
                PdfPageExtraction(
                    page_number=page_number,
                    method="ocr",
                    char_count=len(merged_text),
                    text=merged_text,
                )
            )
    finally:
        document.close()

    provider_name = resolved_provider.name if resolved_provider is not None else "none"
    text = "\n\n".join(page.text for page in pages if page.text).strip()

    return PdfExtractionResult(
        text=text,
        page_count=len(pages),
        pages=pages,
        text_layer_page_count=sum(1 for p in pages if p.method == "text_layer"),
        ocr_page_count=sum(1 for p in pages if p.method == "ocr"),
        ocr_unavailable_page_count=sum(1 for p in pages if p.method == "ocr_unavailable"),
        ocr_provider=provider_name,
        truncated=truncated,
    )


def _import_pymupdf():
    try:
        import pymupdf

        return pymupdf
    except ImportError:
        try:
            import fitz

            return fitz
        except ImportError as exc:
            raise PdfExtractionError(
                "PyMuPDF is not installed. Install 'pymupdf' to parse PDF files."
            ) from exc


def _render_page_png(page, dpi: int) -> bytes:
    pixmap = page.get_pixmap(dpi=dpi)
    return pixmap.tobytes("png")


def _format_seal_texts(seal_texts: tuple[str, ...]) -> str:
    cleaned = [text.strip() for text in seal_texts if text and text.strip()]
    if not cleaned:
        return ""
    return "\n[印章] " + "; ".join(cleaned)


def _short_reason(exc: Exception) -> str:
    reason = str(exc).strip().splitlines()
    return reason[0] if reason else exc.__class__.__name__
