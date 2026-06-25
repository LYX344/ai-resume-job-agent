from pydantic import BaseModel, Field

from app.models.agent import AgentCheckpointInfo, AgentStep
from app.models.memory import MemoryProfile
from app.models.rag import RagSource
from app.models.session import SessionState


class AgentState(BaseModel):
    query: str
    session_id: str | None = None
    use_knowledge_base: bool = True
    top_k: int = 5
    model: str | None = None
    temperature: float | None = 0.2
    max_tokens: int | None = None

    intent: str = "unknown"
    needs_retrieval: bool = False
    selected_tool: str | None = None
    tool_result: dict = Field(default_factory=dict)
    proposed_tool_calls: list[dict] = Field(default_factory=list)
    executed_tool_calls: list[dict] = Field(default_factory=list)
    tool_call_rounds: int = 0
    tool_call_limit_reached: bool = False
    provider_error: str | None = None
    session: SessionState | None = None
    memory_profile: MemoryProfile | None = None
    memory_used: bool = False
    answer: str = ""
    sources: list[RagSource] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)
    checkpoint: AgentCheckpointInfo | None = None
    finish_reason: str | None = None
    usage: dict | None = None
