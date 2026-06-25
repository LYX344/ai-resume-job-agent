from pydantic import BaseModel, Field


class TextEmbedding(BaseModel):
    text: str = Field(min_length=1)
    embedding: list[float] = Field(min_length=1)
