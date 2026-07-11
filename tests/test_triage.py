import asyncio

from bim_coordination_ai.models import CoordinationIssue, Discipline, Priority
from bim_coordination_ai.triage import RulesTriageEngine


def triage(issue: CoordinationIssue):
    return asyncio.run(RulesTriageEngine().triage(issue))


def test_deep_structural_clash_is_high_priority() -> None:
    result = triage(
        CoordinationIssue(
            id="CL-001",
            title="Supply duct clashes with structural beam",
            distance_mm=-75,
        )
    )

    assert result.priority == Priority.HIGH
    assert result.lead_discipline == Discipline.MEP
    assert result.requires_human_review is False


def test_life_safety_issue_is_escalated() -> None:
    result = triage(
        CoordinationIssue(
            id="CL-002",
            title="Fire egress route is blocked",
            disciplines=[Discipline.ARCHITECTURE, Discipline.FIRE],
        )
    )

    assert result.priority == Priority.CRITICAL
    assert result.lead_discipline == Discipline.FIRE
    assert result.requires_human_review is True


def test_unknown_owner_requires_review() -> None:
    result = triage(
        CoordinationIssue(
            id="CL-003",
            title="Unclassified coordination item",
        )
    )

    assert result.lead_discipline == Discipline.UNKNOWN
    assert result.requires_human_review is True
