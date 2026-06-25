"""OCR provider abstraction for scanned PDF pages.

This module decouples the PDF extraction pipeline from any single OCR engine.
Three providers are supported:

- ``PaddleOcrProvider``: local, offline, domestic-friendly. Handles mixed
  Chinese/English and best-effort seal (公章) text via PaddleOCR. Heavy
  dependency; imported lazily so the rest of the project runs without it.
- ``ApiOcrProvider``: OpenAI-compatible vision LLM. Strong on stamps/seals,
  mixed languages and messy layout. Needs network + key.
- ``NullOcrProvider``: used when OCR is disabled; raises a clear error so the
  extraction pipeline can degrade gracefully instead of crashing.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import httpx

from app.core.config import Settings
from app.core.config import settings as default_settings


class OcrError(RuntimeError):
    """Base class for OCR errors."""


class OcrConfigurationError(OcrError):
    """Raised when OCR is requested but not properly configured/installed."""


class OcrProviderError(OcrError):
    """Raised when an OCR engine fails at runtime."""


_OCR_PROMPT = (
    "You are an OCR engine. Transcribe ALL text visible in this image exactly, "
    "including text inside stamps/seals (公章) and mixed Chinese/English content. "
    "Preserve the natural reading order. Output only the transcribed text as "
    "plain text or Markdown, with no commentary, no explanations and no code fences."
)


@dataclass(frozen=True)
class OcrPageResult:
    """Result of running OCR on a single page image."""

    text: str
    provider: str
    seal_texts: tuple[str, ...] = ()


@runtime_checkable
class OcrProvider(Protocol):
    @property
    def name(self) -> str: ...

    def ocr_image(self, image: bytes) -> OcrPageResult: ...


class NullOcrProvider:
    """No-op provider used when OCR is disabled."""

    name = "none"

    def ocr_image(self, image: bytes) -> OcrPageResult:
        raise OcrConfigurationError(
            "OCR is not enabled. Set PDF_OCR_ENABLED=true and PDF_OCR_PROVIDER "
            "to 'paddleocr' or 'api' to process scanned pages."
        )


class PaddleOcrProvider:
    """Local PaddleOCR engine (lazy-imported).

    Supports mixed Chinese/English recognition. Seal/stamp text is recognised
    on a best-effort basis by the underlying detector. The engine is heavy, so
    it is only imported and constructed on first use.
    """

    name = "paddleocr"

    def __init__(self, *, language: str = "ch", enable_seal: bool = True) -> None:
        self._language = language
        self._enable_seal = enable_seal
        self._engine = None

    def _ensure_engine(self) -> None:
        if self._engine is not None:
            return
        try:
            from paddleocr import PaddleOCR
        except Exception as exc:  # ImportError or backend init error
            raise OcrConfigurationError(
                "PaddleOCR is not installed. Install 'paddleocr' and "
                "'paddlepaddle', or set PDF_OCR_PROVIDER=api. "
                f"Import error: {exc}"
            ) from exc
        # paddlepaddle 3.x PIR + oneDNN can fail on some CPUs with
        # "ConvertPirAttribute2RuntimeAttribute not support". Disabling mkldnn
        # avoids that path; fall back to defaults if the kwarg is unsupported.
        attempts = (
            {"lang": self._language, "enable_mkldnn": False},
            {"lang": self._language},
        )
        last_error: Exception | None = None
        for kwargs in attempts:
            try:
                self._engine = PaddleOCR(**kwargs)
                return
            except Exception as exc:
                last_error = exc
        raise OcrProviderError(f"Failed to initialize PaddleOCR: {last_error}")

    def ocr_image(self, image: bytes) -> OcrPageResult:
        self._ensure_engine()
        try:
            array = _png_bytes_to_array(image)
            raw = self._predict(array)
            texts = _extract_paddle_texts(raw)
        except OcrError:
            raise
        except Exception as exc:
            raise OcrProviderError(f"PaddleOCR recognition failed: {exc}") from exc
        return OcrPageResult(text="\n".join(texts), provider=self.name)

    def _predict(self, array):
        engine = self._engine
        # PaddleOCR 3.x uses predict(); 2.x uses ocr(). Support both.
        if hasattr(engine, "predict"):
            return engine.predict(array)
        return engine.ocr(array)


class ApiOcrProvider:
    """OpenAI-compatible vision LLM used as an OCR engine."""

    name = "api"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def ocr_image(self, image: bytes) -> OcrPageResult:
        encoded = base64.b64encode(image).decode("ascii")
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _OCR_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{encoded}"},
                        },
                    ],
                }
            ],
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            response = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise OcrProviderError(f"OCR API request failed: {exc}") from exc

        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OcrProviderError("OCR API returned an unexpected response shape.") from exc
        if not isinstance(text, str):
            raise OcrProviderError("OCR API returned non-text content.")
        return OcrPageResult(text=text.strip(), provider=self.name)


def get_ocr_provider(settings: Settings | None = None) -> OcrProvider:
    """Build an OCR provider from settings."""
    settings = settings or default_settings
    if not settings.pdf_ocr_enabled:
        return NullOcrProvider()

    provider = (settings.pdf_ocr_provider or "").strip().lower()
    if provider in ("", "none"):
        return NullOcrProvider()
    if provider == "paddleocr":
        return PaddleOcrProvider(
            language=settings.pdf_ocr_language,
            enable_seal=settings.pdf_ocr_enable_seal,
        )
    if provider == "api":
        if not settings.pdf_ocr_api_base_url or not settings.pdf_ocr_api_key:
            raise OcrConfigurationError(
                "API OCR provider requires PDF_OCR_API_BASE_URL and PDF_OCR_API_KEY."
            )
        return ApiOcrProvider(
            base_url=settings.pdf_ocr_api_base_url,
            api_key=settings.pdf_ocr_api_key,
            model=settings.pdf_ocr_api_model,
            timeout_seconds=settings.pdf_ocr_timeout_seconds,
        )
    raise OcrConfigurationError(f"Unknown OCR provider: {provider}")


def _png_bytes_to_array(image: bytes):
    """Decode PNG bytes into an RGB numpy array for PaddleOCR."""
    try:
        import io

        import numpy as np
        from PIL import Image
    except Exception as exc:
        raise OcrConfigurationError(
            f"PaddleOCR image decoding requires numpy and Pillow: {exc}"
        ) from exc
    with Image.open(io.BytesIO(image)) as pil_image:
        return np.array(pil_image.convert("RGB"))


def _extract_paddle_texts(raw) -> list[str]:
    """Extract recognised text lines from PaddleOCR 2.x/3.x output."""
    texts: list[str] = []
    if raw is None:
        return texts

    for item in _iter_paddle_items(raw):
        # PaddleOCR 3.x: dict-like with "rec_texts".
        rec_texts = _get_field(item, "rec_texts")
        if isinstance(rec_texts, (list, tuple)):
            texts.extend(str(text) for text in rec_texts if text)
            continue
        # PaddleOCR 2.x: [box, (text, score)].
        line_text = _extract_legacy_line_text(item)
        if line_text:
            texts.append(line_text)
    return [text for text in (t.strip() for t in texts) if text]


def _iter_paddle_items(raw):
    if isinstance(raw, (list, tuple)):
        for entry in raw:
            yield entry
    else:
        yield raw


def _get_field(item, key):
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _extract_legacy_line_text(item) -> str | None:
    if not isinstance(item, (list, tuple)):
        return None
    if len(item) >= 2 and isinstance(item[1], (list, tuple)) and item[1]:
        return str(item[1][0])
    return None
