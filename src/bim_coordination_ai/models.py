from datetime import date, datetime
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


class DocumentType(StrEnum):
    DWG = "dwg"
    PDF = "pdf"
    IFC = "ifc"
    RVT = "rvt"
    OTHER = "other"


class TIDPStatus(StrEnum):
    ON_TRACK = "on_track"
    DUE_SOON = "due_soon"      # within TIDP_RESPONSE_WINDOW_DAYS
    OVERDUE = "overdue"
    RESPONDED = "responded"
    PENDING = "pending"        # no received date yet, still ahead of window


# Days within which a TIDP response is considered urgent
TIDP_RESPONSE_WINDOW_DAYS = 14


# ── Clash / coordination issue ────────────────────────────────────────────────

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


# ── TIDP tracking ─────────────────────────────────────────────────────────────

class TIDPEntry(BaseModel):
    """One row in the Target Information Delivery Plan."""

    entry_id: str = Field(description="Unique TIDP row identifier")
    title: str = Field(description="Information package / transmittal title")
    discipline: Discipline
    required_by: date = Field(description="Target delivery / response date")
    received_date: date | None = Field(
        default=None,
        description="Date information was actually received; None if not yet received",
    )
    responded_date: date | None = Field(
        default=None,
        description="Date BIM team submitted response/update; None if outstanding",
    )
    transmittal_ref: str = Field(default="", description="Transmittal or document reference number")
    notes: str = ""


class TIDPCheckResult(BaseModel):
    entry_id: str
    title: str
    discipline: Discipline
    status: TIDPStatus
    days_remaining: int = Field(
        description="Days until required_by (negative when overdue)",
    )
    required_by: date
    received_date: date | None
    responded_date: date | None
    action_required: str
    priority: Priority


class TIDPBatch(BaseModel):
    entries: list[TIDPEntry]
    as_of: date | None = Field(
        default=None,
        description="Reference date for calculation; defaults to today",
    )


class TIDPBatchResult(BaseModel):
    results: list[TIDPCheckResult]
    overdue_count: int
    due_soon_count: int
    on_track_count: int
    responded_count: int


# ── Document comparison ───────────────────────────────────────────────────────

class DocumentRevision(BaseModel):
    """Metadata for one document version (received or BIM output)."""

    doc_id: str
    filename: str
    doc_type: DocumentType
    discipline: Discipline
    revision: str = Field(description="Revision code, e.g. P01, C02, Rev3")
    issue_date: date = Field(description="Date on the document title block or received date")
    issued_by: str = Field(default="", description="Originating party or system")
    content_summary: str = Field(
        default="",
        description="Optional free-text extract from document (OCR or human-provided) for AI diff",
    )


class Discrepancy(BaseModel):
    description: str
    severity: Priority
    location: str | None = None
    element_ref: str | None = None
    recommendation: str = ""


class DocumentComparisonRequest(BaseModel):
    received: DocumentRevision = Field(description="Document received from external party")
    bim_output: DocumentRevision = Field(description="BIM team's latest issued output")


class DocumentComparisonResult(BaseModel):
    doc_id_received: str
    doc_id_bim: str
    discrepancies: list[Discrepancy]
    discrepancy_count: int
    summary: str
    requires_human_review: bool
    confidence: float = Field(ge=0, le=1)


# ── IFC model quality checks ───────────────────────────────────────────────────

class NamingIssue(BaseModel):
    element_id: str
    element_class: str
    name: str
    issue: str
    severity: Priority


class IFCTypeIssue(BaseModel):
    element_id: str
    element_class: str
    name: str
    issue: str


class OmniclassIssue(BaseModel):
    element_id: str
    element_class: str
    name: str
    issue: str


class IFCCheckSummary(BaseModel):
    file_path: str
    project_name: str
    ifc_schema: str = Field(description="IFC schema version, e.g. IFC4 or IFC2X3")
    total_elements: int
    naming_pass: int
    naming_fail: int
    type_eligible: int
    type_pass: int
    type_fail: int
    omniclass_pass: int
    omniclass_fail: int
    overall_compliance_pct: float = Field(ge=0, le=100)
    naming_issues: list[NamingIssue] = Field(default_factory=list)
    type_issues: list[IFCTypeIssue] = Field(default_factory=list)
    omniclass_issues: list[OmniclassIssue] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class IFCCheckRequest(BaseModel):
    file_path: str = Field(description="Absolute or project-relative path to the IFC file")
    naming_pattern: str | None = Field(
        default=None,
        description=(
            "Regex pattern elements must match. "
            "Default: ISO 19650-style [DISC]-[TYPE]-[REF], e.g. AR-WALL-L03-001"
        ),
    )
    omniclass_required: bool = Field(
        default=True,
        description="Whether missing Omniclass classification is reported as an issue",
    )


# ── 5D BIM quantity take-off ──────────────────────────────────────────────────

class CostRate(BaseModel):
    """Unit cost rate for a given IFC element class."""

    element_class: str = Field(description="IFC class, e.g. IfcWall")
    rate: float = Field(description="Cost per unit (m², m³, nr, or m)")
    unit: str = Field(description="Unit of measure: m2, m3, nr, m")
    currency: str = "USD"


class QuantityItem(BaseModel):
    element_class: str
    element_id: str
    name: str
    storey: str = ""
    discipline: Discipline
    quantity_type: str = Field(description="area | volume | count | length")
    quantity_value: float
    unit: str
    rate: float | None = None
    cost: float | None = None


class QTOSummary(BaseModel):
    element_class: str
    discipline: Discipline
    count: int
    total_quantity: float
    unit: str
    quantity_type: str
    total_cost: float | None = None


class QTOResult(BaseModel):
    file_path: str
    project_name: str
    currency: str
    items: list[QuantityItem]
    summary: list[QTOSummary]
    grand_total_cost: float | None = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class QTORequest(BaseModel):
    file_path: str = Field(description="Absolute or project-relative path to the IFC file")
    rates: list[CostRate] = Field(
        default_factory=list,
        description="Optional unit cost rates; omit for quantity-only output",
    )
    currency: str = "USD"


# ── Unified IFC report ────────────────────────────────────────────────────────

class ReportFormat(StrEnum):
    HTML = "html"
    EXCEL = "excel"


class ReportRequest(BaseModel):
    file_path: str
    naming_pattern: str | None = None
    omniclass_required: bool = True
    rates: list[CostRate] = Field(default_factory=list)
    currency: str = "USD"
    format: ReportFormat = ReportFormat.HTML
