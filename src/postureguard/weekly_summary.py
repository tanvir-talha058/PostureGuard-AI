"""A once-a-week note naming where posture held up worst.

Purely informational: presentation over aggregates :class:`SessionStore` already
computes for the History screen, gated by a persisted "last shown" date rather than
anything detection-related. Turning it off touches nothing else.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .session import SessionStore

#: Days between summaries.
INTERVAL_DAYS = 7
#: Below this much tracked time in the window, a summary would be more noise than
#: signal — a couple of minutes on a Tuesday does not make a "worst hour" claim.
MIN_TRACKED_SECONDS = 3600


@dataclass
class WeeklySummaryGate:
    """Tracks when a summary was last shown, so it fires on a cadence, not a whim."""

    last_shown: str = ""

    def due(self, today: date | None = None) -> bool:
        """True once a week has passed since the last summary.

        An empty `last_shown` — a fresh install, or one from before this feature
        existed — is never immediately due. There is nothing to summarize on day one,
        and firing on first launch would read as a bug, not a feature. The caller is
        expected to seed `last_shown` to today the first time it sees an empty value.
        """
        if not self.last_shown:
            return False
        try:
            last = date.fromisoformat(self.last_shown)
        except ValueError:
            return True
        return (today or date.today()) - last >= timedelta(days=INTERVAL_DAYS)

    def mark_shown(self, today: date | None = None) -> None:
        self.last_shown = (today or date.today()).isoformat()

    def to_state(self) -> dict:
        return {"last_shown": self.last_shown}

    @classmethod
    def restore(cls, state: dict) -> "WeeklySummaryGate":
        value = state.get("last_shown")
        return cls(last_shown=value if isinstance(value, str) else "")

    def save_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_state()), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "WeeklySummaryGate":
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(state, dict):
            return cls()
        return cls.restore(state)


def build_message(store: SessionStore, today: date | None = None) -> str | None:
    """The week's headline in one line, or None if there isn't enough to say.

    Names the single worst hour of the day, weighted by how much time was actually
    tracked there — the same "weakest hour" the History screen already surfaces, just
    delivered instead of waiting to be looked up.
    """
    summaries = store.daily_summaries(days=INTERVAL_DAYS, today=today)
    tracked_total = sum(s.tracked_seconds for s in summaries)
    if tracked_total < MIN_TRACKED_SECONDS:
        return None

    profile = [h for h in store.hourly_profile(days=INTERVAL_DAYS, today=today) if h.tracked_seconds > 60]
    worst = min(profile, key=lambda h: h.score, default=None)
    average = 100.0 * sum(s.in_tolerance_seconds for s in summaries) / tracked_total

    if worst is None:
        return f"Averaged {average:.0f}% in tolerance this week."
    return (
        f"Averaged {average:.0f}% in tolerance this week. "
        f"{worst.hour:02d}:00 held up worst, at {worst.score:.0f}%."
    )
