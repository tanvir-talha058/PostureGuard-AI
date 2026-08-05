"""Turns a week of posture history into a short, personalized note via the Claude API.

Sends aggregate numbers only — daily scores, the worst hour, minutes spent in each
fault type — never frames, landmarks, or per-frame metrics. The caller (app.py) falls
back to :func:`postureguard.weekly_summary.build_message`'s static one-liner whenever
`generate_message` returns None.
"""

from __future__ import annotations

import json
from datetime import date

from ..rules import FAULT_TITLES
from ..session import SessionStore
from ..weekly_summary import INTERVAL_DAYS, MIN_TRACKED_SECONDS
from .client import ask

_SYSTEM_PROMPT = (
    "You write a one-paragraph weekly posture note for a desk-work posture app called "
    "PostureGuard. The tone is that of a measuring instrument, not a wellness app: "
    "plain, specific, no moralizing, no exclamation points, no emoji. You are given "
    "aggregate statistics for the past week — daily in-tolerance percentages, the "
    "worst hour of the day, and minutes spent in each named fault. Write 2-4 sentences "
    "naming the pattern, not just the numbers. Do not invent numbers not present in "
    "the data. Do not give medical advice."
)


def build_stats_payload(
    store: SessionStore, days: int = INTERVAL_DAYS, today: date | None = None
) -> dict | None:
    """Pure aggregate summary of the last `days`. None when there is too little
    tracked time to say anything meaningful — the same gate
    :func:`postureguard.weekly_summary.build_message` uses.
    """
    summaries = store.daily_summaries(days=days, today=today)
    tracked_total = sum(s.tracked_seconds for s in summaries)
    if tracked_total < MIN_TRACKED_SECONDS:
        return None

    profile = [h for h in store.hourly_profile(days=days, today=today) if h.tracked_seconds > 60]
    worst = min(profile, key=lambda h: h.score, default=None)
    average = 100.0 * sum(s.in_tolerance_seconds for s in summaries) / tracked_total
    fault_minutes = {
        FAULT_TITLES[kind]: round(seconds / 60)
        for kind, seconds in store.fault_breakdown(days=days, today=today).items()
        if seconds >= 60
    }

    return {
        "days_tracked": len(summaries),
        "average_in_tolerance_percent": round(average, 1),
        "worst_hour": f"{worst.hour:02d}:00" if worst else None,
        "worst_hour_score_percent": round(worst.score, 1) if worst else None,
        "fault_minutes": fault_minutes,
    }


def generate_message(payload: dict, api_key: str) -> str | None:
    """The AI weekly note, or None on any failure — the caller falls back to the
    existing static one-liner."""
    return ask(_SYSTEM_PROMPT, json.dumps(payload), api_key, effort="low")
