import logging
import sys
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response


REQUEST_LOGGER_NAME = "app.request"


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        import json

        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in (
            "event",
            "request_id",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "client_host",
        ):
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(level: str = "INFO") -> None:
    root_logger = logging.getLogger()
    if not any(getattr(handler, "_personal_agent_json", False) for handler in root_logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonLogFormatter())
        handler._personal_agent_json = True  # type: ignore[attr-defined]
        root_logger.addHandler(handler)

    root_logger.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)


def log_http_request(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    client_host: str | None,
) -> None:
    logging.getLogger(REQUEST_LOGGER_NAME).info(
        "http_request",
        extra={
            "event": "http_request",
            "request_id": request_id,
            "method": method,
            "path": path,
            "status_code": status_code,
            "duration_ms": round(duration_ms, 2),
            "client_host": client_host,
        },
    )


def install_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_logging_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        started_at = time.perf_counter()
        client_host = request.client.host if request.client else None

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started_at) * 1000
            log_http_request(
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=duration_ms,
                client_host=client_host,
            )
            raise

        duration_ms = (time.perf_counter() - started_at) * 1000
        response.headers["x-request-id"] = request_id
        log_http_request(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            client_host=client_host,
        )
        return response
