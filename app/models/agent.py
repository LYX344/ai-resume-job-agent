from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.rag import RagSource


AgentStepStatus = Literal["completed", "skipped"]


class AgentRunRequest(BaseModel):
    query: str = Field(min_length=1)
    session_id: str | None = Field(default=None, min_length=1, max_length=80)
    use_knowledge_base: bool = True
    top_k: int = Field(default=5, ge=1, le=20)
    model: str | None = None
    temperature: float | None = Field(default=0.2, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)


class AgentStep(BaseModel):
    name: str
    status: AgentStepStatus
    detail: str
    data: dict[str, Any] = Field(default_factory=dict)


class AgentCheckpointInfo(BaseModel):
    thread_id: str
    checkpoint_id: str | None = None
    checkpoint_namespace: str = ""
    step: int | None = None
    created_at: str | None = None
    backend: Literal["in_memory", "local_file"] = "in_memory"
    durable: bool = False
    production_ready: bool = False


class AgentCheckpointSnapshotResponse(AgentCheckpointInfo):
    parent_checkpoint_id: str | None = None
    pending_write_count: int = 0
    state_channel_keys: list[str] = Field(default_factory=list)
    resume_supported: bool = False
    human_in_the_loop_supported: bool = False
    notes: list[str] = Field(default_factory=list)


class AgentCheckpointHistoryResponse(BaseModel):
    thread_id: str
    checkpoint_count: int = 0
    limit: int
    checkpoints: list[AgentCheckpointSnapshotResponse] = Field(default_factory=list)


class AgentRunResponse(BaseModel):
    answer: str
    intent: str
    session_id: str | None = None
    memory_used: bool = False
    used_knowledge_base: bool
    sources: list[RagSource] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)
    checkpoint: AgentCheckpointInfo | None = None
    model: str | None = None
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


class JobApplicationRequest(BaseModel):
    jd_text: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class JobApplicationStepInfo(BaseModel):
    agent: str
    status: str
    detail: str = ""


class JobApplicationResponse(BaseModel):
    resume_summary: str
    match_analysis: str
    application_material: str
    steps: list[JobApplicationStepInfo] = Field(default_factory=list)


class JobApplicationReviewRequest(BaseModel):
    jd_text: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class JobApplicationResumeRequest(BaseModel):
    thread_id: str = Field(min_length=1)
    note: str = ""
    approved: bool = True


class JobApplicationReviewResponse(BaseModel):
    status: str
    thread_id: str
    resume_summary: str = ""
    match_analysis: str = ""
    application_material: str = ""
    review_payload: dict[str, Any] | None = None
    steps: list[JobApplicationStepInfo] = Field(default_factory=list)
