import asyncio

from .models import CoordinationIssue, TriageResult
from .triage import TriageEngine


class CoordinationService:
    def __init__(self, engine: TriageEngine) -> None:
        self.engine = engine

    async def triage_batch(
        self, issues: list[CoordinationIssue]
    ) -> list[TriageResult]:
        return await asyncio.gather(*(self.engine.triage(issue) for issue in issues))
