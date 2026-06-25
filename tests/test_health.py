from fastapi.testclient import TestClient

from app.api.dependencies import get_mysql_store, get_redis_store
from app.main import app


def test_health_check_returns_app_status() -> None:
    client = TestClient(app)

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "app_name": "AI Resume Job Agent",
        "app_env": "development",
        "app_version": "0.1.0",
    }


def test_cors_allows_local_frontend_origin() -> None:
    client = TestClient(app)

    response = client.get(
        "/api/v1/health",
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


class FakeRedisStore:
    async def ping(self) -> bool:
        return True


def test_redis_health_check_returns_connected() -> None:
    app.dependency_overrides[get_redis_store] = lambda: FakeRedisStore()
    client = TestClient(app)

    response = client.get("/api/v1/health/redis")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "redis": "connected"}


class FakeMySQLStore:
    async def ping(self) -> bool:
        return True


def test_mysql_health_check_returns_connected() -> None:
    app.dependency_overrides[get_mysql_store] = lambda: FakeMySQLStore()
    client = TestClient(app)

    response = client.get("/api/v1/health/mysql")

    app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mysql": "connected"}
