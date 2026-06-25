from pydantic import BaseModel, Field


class TraceStep(BaseModel):
    name: str
    status: str
    detail: str = ""


class TraceRecord(BaseModel):
    trace_id: str
    kind: str
    query: str = ""
    intent: str = ""
    started_at: str
    duration_ms: float
    step_count: int = Field(ge=0)
    steps: list[TraceStep] = Field(default_factory=list)
    usage: dict | None = None
    model: str | None = None
    tool_calls: list[dict] = Field(default_factory=list)
