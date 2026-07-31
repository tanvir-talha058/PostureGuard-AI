"""Backing sensitivity off on its own, after enough same-day snoozes.

Snoozing repeatedly is the most direct feedback a user can give — more direct than any
slider — that detection is too twitchy for how they actually sit. Waiting for them to
find Settings mid-workday to say so is asking a lot of someone already annoyed enough to
be reaching for Snooze a third time. This counts same-day snoozes and, once, nudges
`sensitivity` down a step on its own — never silently: the caller is expected to tell
the user it happened.

Pure counting logic, no camera or UI — same shape as :class:`stretches.BreakTimer`,
including how its count survives a restart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

#: Same-day snoozes before sensitivity backs off.
SNOOZE_THRESHOLD = 3
#: How much to reduce `sensitivity` by, once, per trigger.
BACKOFF_STEP = 0.15
#: Never back off below this — matches the floor `Config.thresholds()` already clamps
#: every threshold to, so a backoff can never produce a sensitivity that clamp silently
#: overrides anyway.
MIN_SENSITIVITY = 0.25


@dataclass
class SnoozeBackoff:
    """Counts snoozes within a day and decides when a backoff is due."""

    day: str = ""
    count: int = 0

    def record(self, today: date | None = None) -> bool:
        """Register one snooze. Returns True on the frame the threshold is crossed.

        Only the exact crossing returns True — the count keeps climbing past it for
        the rest of the day without re-triggering, so a bad afternoon backs
        sensitivity off once, not once per snooze.
        """
        current = (today or date.today()).isoformat()
        if current != self.day:
            self.day = current
            self.count = 0
        self.count += 1
        return self.count == SNOOZE_THRESHOLD

    @staticmethod
    def next_sensitivity(current: float) -> float:
        return max(round(current - BACKOFF_STEP, 2), MIN_SENSITIVITY)

    # --- persistence ------------------------------------------------------------

    def to_state(self) -> dict:
        return {"day": self.day, "count": self.count}

    @classmethod
    def restore(cls, state: dict) -> SnoozeBackoff:
        day = state.get("day")
        count = state.get("count")
        if not isinstance(day, str) or not isinstance(count, int):
            return cls()
        return cls(day=day, count=count)

    def save_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_state()), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SnoozeBackoff:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(state, dict):
            return cls()
        return cls.restore(state)
