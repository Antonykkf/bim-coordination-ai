from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Discipline(StrEnum):
    ARCHITECTURE = "architecture"
    STRUCTURE = "structure"
    MEP = "mep"
    FIRE = "fire"
    CIVIL = "civil"
    UNKNOWN = "unknown"


class Priority(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CoordinationIssue(BaseModel):
    id: str = Field(description="Stable issue or clash identifier")
    title: str
    description: str = ""
    source: str = Field(default="manual", description="ACC, BCF, Solibri, Navisworks, or manual")
    location: str | None = None
    element_ids: list[str] = Field(default_factory=list)
    disciplines: list[Discipline] = Field(default_factory=list)
    distance_mm: float | None = Field(
        default=None,
        description="Signed clearance; negative values indicate penetration",
    )
    due_date: datetime | None = None


class TriageResult(BaseModel):
    issue_id: str
    priority: Priority
    lead_discipline: Discipline
    action: str
    rationale: str
    confidence: float = Field(ge=0, le=1)
    requires_human_review: bool
    tags: list[str] = Field(default_factory=list)


class TriageBatch(BaseModel):
    issues: list[CoordinationIssue]


class TriageBatchResult(BaseModel):
    results: list[TriageResult]
