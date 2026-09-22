"""Tests for TIDP 14-day SLA tracker."""

from datetime import date

import pytest

from bim_coordination_ai.models import (
    TIDP_RESPONSE_WINDOW_DAYS,
    Discipline,
    Priority,
    TIDPBatch,
    TIDPEntry,
    TIDPStatus,
)
from bim_coordination_ai.tidp import TIDPTracker

tracker = TIDPTracker()

TODAY = date(2026, 7, 11)


def _entry(**kwargs) -> TIDPEntry:
    defaults = dict(
        entry_id="T-001",
        title="Structural drawings for Level 3",
        discipline=Discipline.STRUCTURE,
        required_by=TODAY,
    )
    defaults.update(kwargs)
    return TIDPEntry(**defaults)


# ── Single entry checks ───────────────────────────────────────────────────────

def test_overdue_is_critical():
    entry = _entry(required_by=date(2026, 7, 1))  # 10 days ago
    result = tracker.check(entry, as_of=TODAY)
    assert result.status == TIDPStatus.OVERDUE
    assert result.priority == Priority.CRITICAL
    assert result.days_remaining == -10
    assert "OVERDUE" in result.action_required


def test_due_today_is_due_soon():
    entry = _entry(required_by=TODAY)
    result = tracker.check(entry, as_of=TODAY)
    assert result.status == TIDPStatus.DUE_SOON
    assert result.priority == Priority.HIGH
    assert result.days_remaining == 0


def test_within_14_days_is_due_soon():
    entry = _entry(required_by=date(2026, 7, 20))  # 9 days away
    result = tracker.check(entry, as_of=TODAY)
    assert result.status == TIDPStatus.DUE_SOON
    assert result.days_remaining == 9


def test_exactly_on_boundary_is_due_soon():
    entry = _entry(required_by=date(2026, 7, 11 + TIDP_RESPONSE_WINDOW_DAYS))
    result = tracker.check(entry, as_of=TODAY)
    assert result.status == TIDPStatus.DUE_SOON


def test_beyond_window_no_received_date_is_pending():
    entry = _entry(required_by=date(2026, 8, 10))  # 30 days away, nothing received
    result = tracker.check(entry, as_of=TODAY)
    assert result.status == TIDPStatus.PENDING
    assert result.priority == Priority.MEDIUM


def test_on_track_when_received_and_ahead():
    entry = _entry(
        required_by=date(2026, 8, 10),
        received_date=date(2026, 7, 5),
    )
    result = tracker.check(entry, as_of=TODAY)
    assert result.status == TIDPStatus.ON_TRACK
    assert result.priority == Priority.LOW


def test_responded_is_low_priority():
    entry = _entry(
        required_by=date(2026, 6, 1),  # past due
        responded_date=date(2026, 5, 30),
    )
    result = tracker.check(entry, as_of=TODAY)
    assert result.status == TIDPStatus.RESPONDED
    assert result.priority == Priority.LOW


# ── Batch checks ──────────────────────────────────────────────────────────────

def test_batch_sorted_overdue_first():
    entries = [
        _entry(entry_id="A", required_by=date(2026, 8, 10)),   # on track
        _entry(entry_id="B", required_by=date(2026, 7, 1)),    # overdue
        _entry(entry_id="C", required_by=date(2026, 7, 18)),   # due soon
    ]
    batch = TIDPBatch(entries=entries, as_of=TODAY)
    result = tracker.check_batch(batch)
    statuses = [r.status for r in result.results]
    assert statuses[0] == TIDPStatus.OVERDUE
    assert statuses[1] == TIDPStatus.DUE_SOON


def test_batch_summary_counts():
    entries = [
        _entry(entry_id="X1", required_by=date(2026, 7, 1)),   # overdue
        _entry(entry_id="X2", required_by=date(2026, 7, 15)),  # due soon
        _entry(entry_id="X3", required_by=date(2026, 8, 20)),  # pending
        _entry(entry_id="X4", required_by=date(2026, 6, 1), responded_date=date(2026, 5, 28)),
    ]
    batch = TIDPBatch(entries=entries, as_of=TODAY)
    result = tracker.check_batch(batch)
    assert result.overdue_count == 1
    assert result.due_soon_count == 1
    assert result.responded_count == 1
