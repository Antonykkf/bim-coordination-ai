import json
import os
from typing import Protocol

import httpx

from .models import CoordinationIssue, Discipline, Priority, TriageResult


class TriageEngine(Protocol):
    async def triage(self, issue: CoordinationIssue) -> TriageResult: ...


class RulesTriageEngine:
    """Safe baseline used when an LLM is not configured or needs review."""

    async def triage(self, issue: CoordinationIssue) -> TriageResult:
        text = f"{issue.title} {issue.description}".lower()
        priority = self._priority(issue, text)
        discipline = self._lead_discipline(issue, text)
        tags = self._tags(text)

        return TriageResult(
            issue_id=issue.id,
            priority=priority,
            lead_discipline=discipline,
            action=self._action(priority, discipline),
            rationale=self._rationale(issue, priority),
            confidence=0.75 if discipline != Discipline.UNKNOWN else 0.45,
            requires_human_review=(
                discipline == Discipline.UNKNOWN or priority == Priority.CRITICAL
            ),
            tags=tags,
        )

    @staticmethod
    def _priority(issue: CoordinationIssue, text: str) -> Priority:
        if any(term in text for term in ("life safety", "egress", "fire rating", "critical")):
            return Priority.CRITICAL
        if issue.distance_mm is not None and issue.distance_mm <= -50:
            return Priority.HIGH
        if any(term in text for term in ("clash", "penetration", "blocked", "collision")):
            return Priority.HIGH
        if issue.distance_mm is not None and issue.distance_mm < 0:
            return Priority.MEDIUM
        return Priority.LOW

    @staticmethod
    def _lead_discipline(issue: CoordinationIssue, text: str) -> Discipline:
        keywords = {
            Discipline.FIRE: ("sprinkler", "fire", "smoke"),
            Discipline.MEP: ("duct", "pipe", "cable", "tray", "mechanical", "electrical"),
            Discipline.STRUCTURE: ("beam", "column", "slab", "structural"),
            Discipline.ARCHITECTURE: ("wall", "door", "ceiling", "facade", "architectural"),
            Discipline.CIVIL: ("drainage", "road", "utility", "civil"),
        }
        for discipline, terms in keywords.items():
            if any(term in text for term in terms):
                return discipline
        return issue.disciplines[0] if issue.disciplines else Discipline.UNKNOWN

    @staticmethod
    def _tags(text: str) -> list[str]:
        tag_terms = ("clash", "clearance", "penetration", "access", "egress", "fire")
        return [term for term in tag_terms if term in text]

    @staticmethod
    def _action(priority: Priority, discipline: Discipline) -> str:
        owner = discipline.value if discipline != Discipline.UNKNOWN else "BIM coordinator"
        if priority in (Priority.CRITICAL, Priority.HIGH):
            return f"Assign to {owner} and review at the next coordination session."
        return f"Assign to {owner} for model review and resolution."

    @staticmethod
    def _rationale(issue: CoordinationIssue, priority: Priority) -> str:
        if issue.distance_mm is not None and issue.distance_mm < 0:
            return (
                f"Detected {abs(issue.distance_mm):g} mm penetration; "
                f"classified as {priority.value}."
            )
        return f"Issue language and discipline context indicate {priority.value} priority."


class OpenAICompatibleTriageEngine:
    def __init__(self, fallback: TriageEngine | None = None) -> None:
        self.api_key = os.environ["AI_API_KEY"]
        self.base_url = os.getenv("AI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("AI_MODEL", "gpt-4.1-mini")
        self.fallback = fallback or RulesTriageEngine()

    async def triage(self, issue: CoordinationIssue) -> TriageResult:
        prompt = (
            "You are a senior BIM coordinator. Triage the issue as JSON with fields: "
            "priority (critical/high/medium/low), lead_discipline "
            "(architecture/structure/mep/fire/civil/unknown), action, rationale, "
            "confidence (0-1), requires_human_review, and tags. "
            "Escalate life-safety decisions for human review.\n\n"
            f"Issue: {issue.model_dump_json()}"
        )
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "response_format": {"type": "json_object"},
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0,
                    },
                )
                response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            return TriageResult(issue_id=issue.id, **json.loads(content))
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            result = await self.fallback.triage(issue)
            result.requires_human_review = True
            result.rationale += " AI service unavailable; rules fallback used."
            return result


def create_triage_engine() -> TriageEngine:
    if os.getenv("AI_API_KEY"):
        return OpenAICompatibleTriageEngine()
    return RulesTriageEngine()
