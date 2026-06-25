"""运行时配置的读取、合并、保存与脱敏视图。

存储：Redis key ``config:runtime``，api 与 worker 进程共享，重启保留。
合并语义：运行时覆盖值优先；为 ``None`` 或空字符串时回退 `.env` 默认值。
"""

from __future__ import annotations

from app.core.config import settings
from app.models.config import (
    ModelConfigView,
    ModelRuntimeConfig,
    RuntimeConfig,
    RuntimeConfigView,
)
from app.services.redis_client import RedisStore

RUNTIME_CONFIG_KEY = "config:runtime"


async def load_runtime_config(redis_store: RedisStore) -> RuntimeConfig:
    """读取运行时配置；读取或解析失败时优雅降级为空配置（即沿用 .env）。"""
    try:
        data = await redis_store.get_json(RUNTIME_CONFIG_KEY)
    except Exception:  # noqa: BLE001 - 配置读取失败不应阻塞主流程
        return RuntimeConfig()
    if not data:
        return RuntimeConfig()
    try:
        return RuntimeConfig.model_validate(data)
    except Exception:  # noqa: BLE001
        return RuntimeConfig()


async def save_runtime_config(redis_store: RedisStore, config: RuntimeConfig) -> None:
    await redis_store.set_json(RUNTIME_CONFIG_KEY, config.model_dump(exclude_none=True))


def merge_section(
    existing: ModelRuntimeConfig, incoming: ModelRuntimeConfig
) -> ModelRuntimeConfig:
    """把前端提交的字段合并进已存配置：None / 空字符串视为“不修改”。"""
    data = existing.model_dump()
    for key, value in incoming.model_dump().items():
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        data[key] = value
    return ModelRuntimeConfig(**data)


def effective_llm(override: ModelRuntimeConfig) -> ModelRuntimeConfig:
    return ModelRuntimeConfig(
        provider=override.provider or settings.llm_provider,
        base_url=override.base_url or settings.llm_base_url,
        model=override.model or settings.llm_model,
        api_key=override.api_key or settings.llm_api_key,
    )


def effective_embedding(override: ModelRuntimeConfig) -> ModelRuntimeConfig:
    return ModelRuntimeConfig(
        provider=override.provider or settings.embedding_provider,
        base_url=override.base_url or settings.embedding_base_url,
        model=override.model or settings.embedding_model,
        api_key=override.api_key or settings.embedding_api_key,
        dimensions=override.dimensions or (settings.embedding_dimensions or None),
    )


def effective_rerank(override: ModelRuntimeConfig) -> ModelRuntimeConfig:
    return ModelRuntimeConfig(
        provider=override.provider or settings.rerank_provider,
        base_url=override.base_url or settings.rerank_base_url,
        model=override.model or settings.rerank_model,
        api_key=override.api_key or settings.rerank_api_key,
    )


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "*" * len(key)
    return f"{key[:4]}{'*' * 6}{key[-4:]}"


def _view(
    effective: ModelRuntimeConfig, *, include_dimensions: bool = False
) -> ModelConfigView:
    return ModelConfigView(
        provider=effective.provider or "",
        base_url=effective.base_url or "",
        model=effective.model or "",
        api_key_set=bool(effective.api_key),
        api_key_masked=mask_api_key(effective.api_key or ""),
        dimensions=effective.dimensions if include_dimensions else None,
    )


def build_runtime_config_view(config: RuntimeConfig) -> RuntimeConfigView:
    return RuntimeConfigView(
        llm=_view(effective_llm(config.llm)),
        embedding=_view(effective_embedding(config.embedding), include_dimensions=True),
        rerank=_view(effective_rerank(config.rerank)),
    )
