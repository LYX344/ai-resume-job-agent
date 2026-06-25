import logging

from fastapi.testclient import TestClient

from app.core.logging import REQUEST_LOGGER_NAME
from app.main import app


def test_request_logging_records_structured_http_fields(caplog) -> None:
    client = TestClient(app)

    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER_NAME):
        response = client.get("/api/v1/health", headers={"x-request-id": "test-request-id"})

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request-id"

    request_records = [
        record for record in caplog.records if getattr(record, "event", None) == "http_request"
    ]
    assert request_records
    record = request_records[-1]
    assert record.request_id == "test-request-id"
    assert record.method == "GET"
    assert record.path == "/api/v1/health"
    assert record.status_code == 200
    assert record.duration_ms >= 0
