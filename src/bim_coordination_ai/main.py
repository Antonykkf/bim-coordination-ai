from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from .models import TriageBatch, TriageBatchResult
from .service import CoordinationService
from .triage import create_triage_engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.coordination_service = CoordinationService(create_triage_engine())
    yield


app = FastAPI(
    title="BIM Coordination AI",
    description="AI-assisted triage for BIM coordination issues and clashes.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/v1/triage", response_model=TriageBatchResult)
async def triage_issues(
    batch: TriageBatch,
    request: Request,
) -> TriageBatchResult:
    results = await request.app.state.coordination_service.triage_batch(batch.issues)
    return TriageBatchResult(results=results)
