from fastapi import APIRouter
from fastapi import Depends

from app.api.dependencies import get_mysql_store, get_redis_store
from app.core.config import settings
from app.models.health import HealthResponse, MySQLHealthResponse, RedisHealthResponse
from app.services.mysql_client import MySQLClientError, MySQLStore
from app.services.redis_client import RedisStore

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        app_env=settings.app_env,
        app_version=settings.app_version,
    )


@router.get("/health/redis", response_model=RedisHealthResponse)
async def redis_health_check(
    redis_store: RedisStore = Depends(get_redis_store),
) -> RedisHealthResponse:
    if await redis_store.ping():
        return RedisHealthResponse(status="ok", redis="connected")
    return RedisHealthResponse(status="error", redis="unavailable")


@router.get("/health/mysql", response_model=MySQLHealthResponse)
async def mysql_health_check(
    mysql_store: MySQLStore = Depends(get_mysql_store),
) -> MySQLHealthResponse:
    try:
        if await mysql_store.ping():
            return MySQLHealthResponse(status="ok", mysql="connected")
    except MySQLClientError:
        pass
    return MySQLHealthResponse(status="error", mysql="unavailable")
