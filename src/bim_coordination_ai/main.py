from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from .document_diff import DocumentDiffService
from .ifc_checker import ifc_checker
from .models import (
    DocumentComparisonRequest,
    DocumentComparisonResult,
    IFCCheckRequest,
    IFCCheckSummary,
    QTORequest,
    QTOResult,
    ReportFormat,
    ReportRequest,
    TIDPBatch,
    TIDPBatchResult,
    TriageBatch,
    TriageBatchResult,
)
from .quantity_takeoff import qto_service
from .report import report_service
from .service import CoordinationService
from .tidp import tidp_tracker
from .triage import create_triage_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.coordination_service = CoordinationService(create_triage_engine())
    app.state.document_diff_service = DocumentDiffService()
    yield


app = FastAPI(
    title="BIM Coordination AI",
    description=(
        "AI-assisted BIM coordination: clash triage, TIDP SLA tracking, "
        "DWG/PDF discrepancy detection, IFC quality checking (naming / type / Omniclass), "
        "5D BIM quantity take-off, and automated HTML + Excel reporting."
    ),
    version="0.3.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


# ── Clash / issue triage ──────────────────────────────────────────────────────

@app.post(
    "/v1/triage",
    response_model=TriageBatchResult,
    summary="Triage BIM coordination clashes and issues",
)
async def triage_issues(batch: TriageBatch, request: Request) -> TriageBatchResult:
    results = await request.app.state.coordination_service.triage_batch(batch.issues)
    return TriageBatchResult(results=results)


# ── TIDP 14-day SLA tracking ──────────────────────────────────────────────────

@app.post(
    "/v1/tidp/check",
    response_model=TIDPBatchResult,
    summary="Check TIDP entries for 14-day response window compliance",
    description=(
        "Evaluates each TIDP entry against its required_by date. "
        "Entries within 14 days are flagged DUE_SOON; past due are OVERDUE (CRITICAL). "
        "Results are sorted by urgency — overdue first."
    ),
)
async def check_tidp(batch: TIDPBatch) -> TIDPBatchResult:
    return tidp_tracker.check_batch(batch)


# ── Document comparison ───────────────────────────────────────────────────────

@app.post(
    "/v1/documents/compare",
    response_model=DocumentComparisonResult,
    summary="Compare received DWG/PDF against BIM output for discrepancies",
    description=(
        "Rules-based comparison of revision, discipline, and issue dates. "
        "If AI_API_KEY is set and content summaries are provided, the LLM enriches "
        "the findings. HIGH/CRITICAL discrepancies are flagged for human BIM coordinator "
        "review before the TIDP response is submitted."
    ),
)
async def compare_documents(
    req: DocumentComparisonRequest, request: Request
) -> DocumentComparisonResult:
    return await request.app.state.document_diff_service.compare(req)


# ── IFC model quality check ───────────────────────────────────────────────────

@app.post(
    "/v1/ifc/check",
    response_model=IFCCheckSummary,
    summary="Validate IFC model: naming convention, IFC type, and Omniclass classification",
    description=(
        "Runs three checks on every IfcProduct in the file. "
        "naming_pattern accepts any Python regex (default: ISO 19650-style [DISC]-[TYPE]-[REF]). "
        "Returns structured issues with severity ratings — CRITICAL/HIGH flag human review."
    ),
)
async def check_ifc(req: IFCCheckRequest) -> IFCCheckSummary:
    try:
        return ifc_checker.check(req)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── 5D BIM quantity take-off ──────────────────────────────────────────────────

@app.post(
    "/v1/ifc/qto",
    response_model=QTOResult,
    summary="Extract 5D BIM quantities from an IFC model",
    description=(
        "Reads Qto_* BaseQuantities from the IFC file. "
        "Supply cost rates per IFC class to get a full 5D cost summary. "
        "Quantities are by element (line items) and by class (summary). "
        "Grand total cost is only included when rates are provided."
    ),
)
async def ifc_qto(req: QTORequest) -> QTOResult:
    try:
        return qto_service.extract(req)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ── Unified IFC dashboard report ──────────────────────────────────────────────

@app.post(
    "/v1/ifc/report",
    summary="Generate HTML dashboard or Excel workbook from IFC model checks + QTO",
    description=(
        "Runs IFC quality check and 5D QTO in one call, then renders the result as "
        "a self-contained HTML dashboard or a multi-sheet Excel workbook. "
        "Set format=html (default) or format=excel in the request body."
    ),
    responses={
        200: {
            "content": {
                "text/html": {},
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {},
            }
        }
    },
)
async def ifc_report(req: ReportRequest) -> Response:
    try:
        check = ifc_checker.check(
            IFCCheckRequest(
                file_path=req.file_path,
                naming_pattern=req.naming_pattern,
                omniclass_required=req.omniclass_required,
            )
        )
        qto = qto_service.extract(
            QTORequest(file_path=req.file_path, rates=req.rates, currency=req.currency)
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if req.format == ReportFormat.EXCEL:
        content = report_service.generate_excel(check, qto)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=bim-report.xlsx"},
        )

    html = report_service.generate_html(check, qto)
    return HTMLResponse(content=html)
