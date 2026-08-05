"""How this week compares to last week — for a trend card, not a table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .rules import FaultKind
from .session import SessionStore

#: Below this much tracked time in a week, a week-over-week comparison is noise.
MIN_TRACKED_SECONDS = 3600

#: A fault needs at least this much time last week to count as "reduced" this week —
#: otherwise a fault that barely occurred looks like a dramatic improvement by dropping
#: to zero.
MIN_FAULT_SECONDS_TO_COMPARE = 60


@dataclass(frozen=True)
class WeeklyTrend:
    this_week_average: float
    last_week_average: float
    most_improved_fault: FaultKind | None
    most_improved_seconds: int


def compute_weekly_trend(store: SessionStore, today: date | None = None) -> WeeklyTrend | None:
    """Compare the 7 days ending at `today` to the 7 days before that.

    Returns None if either week doesn't have enough tracked time to compare fairly.
    """
    end = today or date.today()
    this_week = store.daily_summaries(days=7, today=end)
    last_week_end = end - timedelta(days=7)
    last_week = store.daily_summaries(days=7, today=last_week_end)

    this_tracked = sum(s.tracked_seconds for s in this_week)
    last_tracked = sum(s.tracked_seconds for s in last_week)
    if this_tracked < MIN_TRACKED_SECONDS or last_tracked < MIN_TRACKED_SECONDS:
        return None

    this_average = 100.0 * sum(s.in_tolerance_seconds for s in this_week) / this_tracked
    last_average = 100.0 * sum(s.in_tolerance_seconds for s in last_week) / last_tracked

    this_faults = store.fault_seconds_in_range(end - timedelta(days=6), end)
    last_faults = store.fault_seconds_in_range(
        last_week_end - timedelta(days=6), last_week_end
    )

    best_fault: FaultKind | None = None
    best_drop = 0
    for kind, last_seconds in last_faults.items():
        if last_seconds < MIN_FAULT_SECONDS_TO_COMPARE:
            continue
        drop = last_seconds - this_faults.get(kind, 0)
        if drop > best_drop:
            best_drop = drop
            best_fault = kind

    return WeeklyTrend(
        this_week_average=this_average,
        last_week_average=last_average,
        most_improved_fault=best_fault,
        most_improved_seconds=best_drop,
    )
