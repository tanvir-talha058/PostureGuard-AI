"""A small, fixed set of milestones — recomputed from history, never stored."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .calibration import Baseline
from .rules import FAULT_TITLES
from .session import SessionStore
from .weekly_trend import compute_weekly_trend

#: A day counts as "clean" once it clears this score with enough tracked time behind it.
CLEAN_DAY_THRESHOLD = 80.0
CLEAN_DAY_MIN_TRACKED_SECONDS = 1800


@dataclass(frozen=True)
class Achievement:
    key: str
    title: str
    description: str
    earned: bool


def compute_achievements(
    store: SessionStore,
    baseline: Baseline | None,
    today: date | None = None,
) -> list[Achievement]:
    """Always returns the same 5 achievements, in the same order, earned or not."""
    streak = store.current_streak(
        threshold=CLEAN_DAY_THRESHOLD,
        min_tracked_seconds=CLEAN_DAY_MIN_TRACKED_SECONDS,
        today=today,
    )
    history = store.daily_summaries(days=365, today=today)
    has_clean_day = any(
        s.tracked_seconds >= CLEAN_DAY_MIN_TRACKED_SECONDS and s.score >= CLEAN_DAY_THRESHOLD
        for s in history
    )
    trend = compute_weekly_trend(store, today=today)
    most_improved = trend.most_improved_fault if trend else None

    return [
        Achievement(
            key="first_calibration",
            title="Calibrated",
            description="Completed your first posture calibration.",
            earned=baseline is not None,
        ),
        Achievement(
            key="first_clean_day",
            title="First clean day",
            description=f"Spent a full day at {CLEAN_DAY_THRESHOLD:.0f}%+ in tolerance.",
            earned=has_clean_day,
        ),
        Achievement(
            key="streak_7",
            title="7-day streak",
            description="Seven consecutive clean days.",
            earned=streak >= 7,
        ),
        Achievement(
            key="streak_30",
            title="30-day streak",
            description="Thirty consecutive clean days.",
            earned=streak >= 30,
        ),
        Achievement(
            key="most_improved",
            title="Most improved",
            description=(
                f"Cut {FAULT_TITLES.get(most_improved, most_improved.value if most_improved else '')} "
                "time versus last week."
                if most_improved
                else "Reduce a fault's time versus last week."
            ),
            earned=most_improved is not None,
        ),
    ]
