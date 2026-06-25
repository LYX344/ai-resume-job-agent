from pydantic import BaseModel, Field


class MemoryProfile(BaseModel):
    profile_id: str = Field(default="default", min_length=1)
    preferences: list[str] = Field(default_factory=list)
    project_context: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    updated_at: str | None = None

    @property
    def item_count(self) -> int:
        return len(self.preferences) + len(self.project_context) + len(self.constraints)
