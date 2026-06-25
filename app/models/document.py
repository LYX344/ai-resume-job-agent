from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


DocumentIndexTaskStatus = Literal["pending", "running", "done", "failed"]


class DocumentMetadata(BaseModel):
    source: str = Field(min_length=1)
    file_name: str = Field(min_length=1)
    file_type: str = Field(min_length=1)


class Document(BaseModel):
    document_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    metadata: DocumentMetadata


class DocumentChunk(BaseModel):
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    start_char: int = Field(ge=0)
    end_char: int = Field(gt=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_char_range(self) -> "DocumentChunk":
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self


class DocumentIngestResponse(BaseModel):
    document_id: str
    file_name: str
    file_type: str
    collection: str = "default"
    chunk_count: int = Field(ge=0)
    indexed_keys: list[str] = Field(default_factory=list)


class DocumentIndexTaskState(BaseModel):
    task_id: str = Field(min_length=1)
    status: DocumentIndexTaskStatus
    file_name: str = Field(min_length=1)
    file_type: str | None = None
    document_id: str | None = None
    chunk_count: int = Field(default=0, ge=0)
    indexed_keys: list[str] = Field(default_factory=list)
    error_message: str | None = None
    error_type: str | None = None
    retryable: bool = False
    created_at: str
    updated_at: str


class DocumentSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)
    collection: str | None = None
    rewrite: bool = False


class DocumentSearchResult(BaseModel):
    key: str
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    distance: float = Field(ge=0)


class DocumentSearchResponse(BaseModel):
    query: str
    top_k: int
    results: list[DocumentSearchResult] = Field(default_factory=list)
