import pymupdf
import pytest

from app.core import config as config_module
from app.rag.pdf_extractor import PdfExtractionError, extract_pdf_text
from app.services.ocr_client import NullOcrProvider, OcrError, OcrPageResult


class FakeOcrProvider:
    name = "fake"

    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    def ocr_image(self, image: bytes) -> OcrPageResult:
        self.calls += 1
        return OcrPageResult(text=self._text, provider=self.name)


class FailingOcrProvider:
    name = "failing"

    def ocr_image(self, image: bytes) -> OcrPageResult:
        raise OcrError("engine down")


def _text_pdf_bytes(text: str, *, fontname: str = "helv") -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), text, fontsize=14, fontname=fontname)
    data = document.tobytes()
    document.close()
    return data


def _blank_pdf_bytes(pages: int = 1) -> bytes:
    document = pymupdf.open()
    for _ in range(pages):
        document.new_page()
    data = document.tobytes()
    document.close()
    return data


def test_extract_text_layer_pdf_uses_text_not_ocr() -> None:
    data = _text_pdf_bytes("Hello World RAG Pipeline FastAPI Redis")
    provider = FakeOcrProvider("should not be used")

    result = extract_pdf_text(data, ocr_provider=provider)

    assert "Hello World RAG Pipeline" in result.text
    assert result.text_layer_page_count == 1
    assert result.ocr_page_count == 0
    assert provider.calls == 0
    assert result.pages[0].method == "text_layer"


def test_extract_scanned_pdf_routes_to_ocr() -> None:
    data = _blank_pdf_bytes()
    provider = FakeOcrProvider("扫描件识别出的中文 and English")

    result = extract_pdf_text(data, ocr_provider=provider)

    assert "扫描件识别出的中文" in result.text
    assert result.ocr_page_count == 1
    assert result.text_layer_page_count == 0
    assert provider.calls == 1
    assert result.ocr_provider == "fake"
    assert result.pages[0].method == "ocr"


def test_extract_scanned_pdf_degrades_when_ocr_unavailable() -> None:
    data = _blank_pdf_bytes()

    result = extract_pdf_text(data, ocr_provider=NullOcrProvider())

    assert result.ocr_unavailable_page_count == 1
    assert result.ocr_page_count == 0
    assert "扫描件" in result.text
    assert result.pages[0].method == "ocr_unavailable"


def test_extract_scanned_pdf_degrades_when_ocr_fails() -> None:
    data = _blank_pdf_bytes()

    result = extract_pdf_text(data, ocr_provider=FailingOcrProvider())

    assert result.ocr_unavailable_page_count == 1
    assert "engine down" in result.text


def test_extract_mixed_chinese_english_text_layer() -> None:
    data = _text_pdf_bytes("项目 AI Resume Job Agent 知识库", fontname="china-s")
    provider = FakeOcrProvider("unused")

    result = extract_pdf_text(data, ocr_provider=provider)

    assert result.text_layer_page_count == 1
    assert "AI Resume Job Agent" in result.text
    assert provider.calls == 0


def test_extract_invalid_pdf_raises() -> None:
    with pytest.raises(PdfExtractionError):
        extract_pdf_text(b"this is not a pdf")


def test_extract_respects_max_pages() -> None:
    data = _blank_pdf_bytes(pages=3)
    custom = config_module.settings.model_copy(update={"pdf_ocr_max_pages": 1})
    provider = FakeOcrProvider("ocr text")

    result = extract_pdf_text(data, settings=custom, ocr_provider=provider)

    assert result.truncated is True
    assert result.page_count == 1
