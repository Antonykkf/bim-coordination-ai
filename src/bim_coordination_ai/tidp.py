"""
TIDP (Target Information Delivery Plan) tracker.

Checks each TIDP entry against its required_by date and the 14-day response
window (TIDP_RESPONSE_WINDOW_DAYS).  All output is advisory; flag OVERDUE and
life-safety items for human review.
"""

from datetime import date

from .models import (
    TIDP_RESPONSE_WINDOW_DAYS,
    Discipline,
    Priority,
    TIDPBatch,
    TIDPBatchResult,
    TIDPCheckResult,
    TIDPEntry,
    TIDPStatus,
)

_STATUS_ORDER: dict[TIDPStatus, int] = {
    TIDPStatus.OVERDUE: 0,
    TIDPStatus.DUE_SOON: 1,
    TIDPStatus.PENDING: 2,
    TIDPStatus.ON_TRACK: 3,
    TIDPStatus.RESPONDED: 4,
}


class TIDPTracker:
    """Evaluate TIDP entries and produce prioritised action items."""

    def check(self, entry: TIDPEntry, as_of: date | None = None) -> TIDPCheckResult:
        today = as_of or date.today()
        days_remaining = (entry.required_by - today).days

        if entry.responded_date is not None:
            status = TIDPStatus.RESPONDED
            priority = Priority.LOW
            action = (
                f"Response submitted on {entry.responded_date}. "
                "File transmittal and update TIDP register."
            )

        elif days_remaining < 0:
            status = TIDPStatus.OVERDUE
            priority = Priority.CRITICAL
            action = (
                f"OVERDUE by {abs(days_remaining)} day(s). "
                "Submit TIDP update immediately and notify BIM lead / client."
            )

        elif days_remaining <= TIDP_RESPONSE_WINDOW_DAYS:
            status = TIDPStatus.DUE_SOON
            priority = Priority.HIGH
            action = (
                f"Due in {days_remaining} day(s) — within the {TIDP_RESPONSE_WINDOW_DAYS}-day "
                "response window. Prepare BIM model update and submit transmittal."
            )

        elif entry.received_date is None:
            # Beyond window, nothing received yet — watch for incoming information
            status = TIDPStatus.PENDING
            priority = Priority.MEDIUM
            action = (
                f"{days_remaining} days until required_by. "
                "Information not yet received. Chase originator if silent within "
                f"{days_remaining - TIDP_RESPONSE_WINDOW_DAYS} day(s)."
            )

        else:
            status = TIDPStatus.ON_TRACK
            priority = Priority.LOW
            action = (
                f"Information received on {entry.received_date}. "
                f"{days_remaining} days remaining to submit TIDP response."
            )

        return TIDPCheckResult(
            entry_id=entry.entry_id,
            title=entry.title,
            discipline=entry.discipline,
            status=status,
            days_remaining=days_remaining,
            required_by=entry.required_by,
            received_date=entry.received_date,
            responded_date=entry.responded_date,
            action_required=action,
            priority=priority,
        )

    def check_batch(self, batch: TIDPBatch) -> TIDPBatchResult:
        as_of = batch.as_of
        results = [self.check(e, as_of) for e in batch.entries]

        # Sort by urgency (overdue first), then by days_remaining ascending
        results.sort(key=lambda r: (_STATUS_ORDER.get(r.status, 9), r.days_remaining))

        return TIDPBatchResult(
            results=results,
            overdue_count=sum(1 for r in results if r.status == TIDPStatus.OVERDUE),
            due_soon_count=sum(1 for r in results if r.status == TIDPStatus.DUE_SOON),
            on_track_count=sum(
                1 for r in results if r.status in (TIDPStatus.ON_TRACK, TIDPStatus.PENDING)
            ),
            responded_count=sum(1 for r in results if r.status == TIDPStatus.RESPONDED),
        )


# Module-level singleton — share across request handlers
tidp_tracker = TIDPTracker()
