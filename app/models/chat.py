from typing import Any, Literal

from pydantic import BaseModel, Field


ChatRole = Literal["system", "developer", "user", "assistant"]


class ChatMessage(BaseModel):
    role: ChatRole
    content: str = Field(min_length=1)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1)
    model: str | None = None
    temperature: float | None = Field(default=0.2, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)


class ChatResponse(BaseModel):
    content: str
    model: str
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


class ChatStreamChunk(BaseModel):
    delta: str
    type: str = "content"

