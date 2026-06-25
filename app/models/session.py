from pydantic import BaseModel, Field

from app.models.chat import ChatMessage


class SessionState(BaseModel):
    session_id: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(default_factory=list)

