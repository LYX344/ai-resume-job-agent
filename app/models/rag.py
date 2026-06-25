from typing import Any

from pydantic import BaseModel, Field


class RagQueryRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    collection: str | None = None
    rewrite: bool = False
    model: str | None = None
    temperature: float | None = Field(default=0.2, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)


class RagSource(BaseModel):
    source_id: int = Field(ge=1)
    key: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    distance: float = Field(ge=0)


class RagQueryResponse(BaseModel):
    answer: str
    model: str | None = None
    sources: list[RagSource] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
