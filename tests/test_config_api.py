from typing import Any

from fastapi.testclient import TestClient

from app.api.dependencies import get_redis_store
from app.core.runtime_config import RUNTIME_CONFIG_KEY
from app.main import app


class FakeRedisStore:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def get_json(self, key: str) -> Any:
        return self._data.get(key)

    async def set_json(
        self, key: str, value: dict[str, Any], *, expire_seconds: int | None = None
    ) -> None:
        self._data[key] = value


def test_get_config_returns_masked_view_without_plaintext_key() -> None:
    store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: store
    client = TestClient(app)
    try:
        response = client.get("/api/v1/config")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    for section in ("llm", "embedding", "rerank"):
        assert section in body
        # 绝不回传明文 api_key 字段
        assert "api_key" not in body[section]
        assert "api_key_masked" in body[section]
        assert "api_key_set" in body[section]


def test_put_config_updates_and_persists() -> None:
    store = FakeRedisStore()
    app.dependency_overrides[get_redis_store] = lambda: store
    client = TestClient(app)
    payload = {
        "embedding": {
            "provider": "openai-compatible",
            "base_url": "https://example.test/v1",
            "model": "custom-embed",
            "api_key": "sk-test-1234567890",
            "dimensions": 1536,
        }
    }
    try:
        put_response = client.put("/api/v1/config", json=payload)
        get_response = client.get("/api/v1/config")
    finally:
        app.dependency_overrides.clear()

    assert put_response.status_code == 200
    put_body = put_response.json()
    assert put_body["embedding"]["model"] == "custom-embed"
    assert put_body["embedding"]["base_url"] == "https://example.test/v1"
    assert put_body["embedding"]["api_key_set"] is True
    assert put_body["embedding"]["api_key_masked"].endswith("7890")
    assert "api_key" not in put_body["embedding"]

    # 已持久化到 Redis，并能再次读取
    assert store._data[RUNTIME_CONFIG_KEY]["embedding"]["model"] == "custom-embed"
    assert get_response.json()["embedding"]["model"] == "custom-embed"


def test_put_config_empty_fields_do_not_override() -> None:
    store = FakeRedisStore()
    store._data[RUNTIME_CONFIG_KEY] = {"embedding": {"model": "keep-me"}}
    app.dependency_overrides[get_redis_store] = lambda: store
    client = TestClient(app)
    try:
        put_response = client.put(
            "/api/v1/config",
            json={"embedding": {"model": "", "base_url": "https://new.test/v1"}},
        )
    finally:
        app.dependency_overrides.clear()

    body = put_response.json()
    assert body["embedding"]["model"] == "keep-me"
    assert body["embedding"]["base_url"] == "https://new.test/v1"
