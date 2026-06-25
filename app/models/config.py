"""运行时模型配置（LLM / 向量化 / Rerank）。

允许在不改 `.env`、不重启后端的情况下，于运行时覆盖大模型、向量化模型和
重排模型的 provider / base_url / model / api_key 等配置。配置存到 Redis，
api 进程与 worker 进程共享，重启后保留。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelRuntimeConfig(BaseModel):
    """单个模型的运行时覆盖配置。

    所有字段可选：为 ``None`` 或空字符串时表示沿用 `.env` 中的默认值。
    """

    provider: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    dimensions: int | None = None  # 仅向量化模型使用


class RuntimeConfig(BaseModel):
    llm: ModelRuntimeConfig = Field(default_factory=ModelRuntimeConfig)
    embedding: ModelRuntimeConfig = Field(default_factory=ModelRuntimeConfig)
    rerank: ModelRuntimeConfig = Field(default_factory=ModelRuntimeConfig)


class ModelConfigView(BaseModel):
    """返回给前端的有效配置视图（API key 脱敏，绝不回传明文）。"""

    provider: str
    base_url: str
    model: str
    api_key_set: bool
    api_key_masked: str
    dimensions: int | None = None


class RuntimeConfigView(BaseModel):
    llm: ModelConfigView
    embedding: ModelConfigView
    rerank: ModelConfigView


class ServiceTestResult(BaseModel):
    ok: bool
    message: str


class ConfigTestResponse(BaseModel):
    embedding: ServiceTestResult
    llm: ServiceTestResult
    rerank: ServiceTestResult
