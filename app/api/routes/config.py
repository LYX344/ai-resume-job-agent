"""运行时模型配置接口：在不改 `.env`、不重启的情况下查看/设置/测试模型配置。"""

from fastapi import APIRouter, Depends, HTTPException
from redis import RedisError

from app.api.dependencies import get_redis_store
from app.core.runtime_config import (
    build_runtime_config_view,
    load_runtime_config,
    merge_section,
    save_runtime_config,
)
from app.models.chat import ChatMessage
from app.models.config import (
    ConfigTestResponse,
    ModelRuntimeConfig,
    RuntimeConfig,
    RuntimeConfigView,
    ServiceTestResult,
)
from app.services.embedding_client import build_embedding_client
from app.services.llm_client import build_llm_client
from app.services.redis_client import RedisStore
from app.services.rerank_client import IdentityRerankClient, build_rerank_client

router = APIRouter(tags=["config"])


@router.get("/config", response_model=RuntimeConfigView)
async def get_config(
    redis_store: RedisStore = Depends(get_redis_store),
) -> RuntimeConfigView:
    config = await load_runtime_config(redis_store)
    return build_runtime_config_view(config)


@router.put("/config", response_model=RuntimeConfigView)
async def update_config(
    update: RuntimeConfig,
    redis_store: RedisStore = Depends(get_redis_store),
) -> RuntimeConfigView:
    existing = await load_runtime_config(redis_store)
    merged = RuntimeConfig(
        llm=merge_section(existing.llm, update.llm),
        embedding=merge_section(existing.embedding, update.embedding),
        rerank=merge_section(existing.rerank, update.rerank),
    )
    try:
        await save_runtime_config(redis_store, merged)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail=f"保存配置失败：{exc}") from exc
    return build_runtime_config_view(merged)


@router.post("/config/test", response_model=ConfigTestResponse)
async def test_config(
    redis_store: RedisStore = Depends(get_redis_store),
) -> ConfigTestResponse:
    """用当前生效配置对各模型做一次最小真实调用，便于验证 key 是否可用。"""
    config = await load_runtime_config(redis_store)
    return ConfigTestResponse(
        embedding=await _test_embedding(config.embedding),
        llm=await _test_llm(config.llm),
        rerank=await _test_rerank(config.rerank),
    )


async def _test_embedding(override: ModelRuntimeConfig) -> ServiceTestResult:
    try:
        client = build_embedding_client(override)
        result = await client.embed_text("ping")
        return ServiceTestResult(ok=True, message=f"OK，向量维度 {len(result.embedding)}")
    except Exception as exc:  # noqa: BLE001 - 测试接口需返回错误信息而非抛出
        return ServiceTestResult(ok=False, message=str(exc))


async def _test_llm(override: ModelRuntimeConfig) -> ServiceTestResult:
    client = build_llm_client(override)
    try:
        result = await client.chat(
            messages=[ChatMessage(role="user", content="ping")],
            max_tokens=1,
        )
        return ServiceTestResult(ok=True, message=f"OK，模型 {result.model}")
    except Exception as exc:  # noqa: BLE001
        return ServiceTestResult(ok=False, message=str(exc))
    finally:
        await client.aclose()


async def _test_rerank(override: ModelRuntimeConfig) -> ServiceTestResult:
    client = build_rerank_client(override)
    if isinstance(client, IdentityRerankClient):
        return ServiceTestResult(ok=True, message="identity（未启用真实重排）")
    try:
        items = await client.rerank("ping", ["hello world", "你好世界"], top_n=1)
        return ServiceTestResult(ok=True, message=f"OK，返回 {len(items)} 条")
    except Exception as exc:  # noqa: BLE001
        return ServiceTestResult(ok=False, message=str(exc))
