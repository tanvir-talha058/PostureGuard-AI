"""Auto-selecting a calibration profile by which monitors are connected.

A baseline captured at a standing desk with one monitor is wrong the moment a laptop
docks into a different arrangement — the same reason the README says to recalibrate
whenever the camera or chair moves applies just as much to the monitor setup, since
that's what determines where you're actually looking and sitting. A saved mapping from
"this set of monitors" to "this profile" lets the switch happen on its own instead of
relying on the user remembering to flip the Settings dropdown by hand.

No camera or UI dependency here — same reasoning as metrics.py and rules.py — so this
is unit-tested directly rather than only through the app.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def fingerprint(screens: list[tuple[str, int, int]]) -> str:
    """A stable identifier for a set of connected monitors.

    Built from name and resolution only, not position or order: a window manager can
    renumber or reorder monitors across reboots without the physical setup actually
    changing, and re-fingerprinting on that noise would make the mapping useless.
    """
    parts = sorted(f"{name}:{width}x{height}" for name, width, height in screens)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


class MonitorProfiles:
    """Persisted mapping from a monitor-arrangement fingerprint to a profile name."""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping: dict[str, str] = dict(mapping or {})

    def get(self, key: str) -> str | None:
        return self._mapping.get(key)

    def remember(self, key: str, profile: str) -> None:
        self._mapping[key] = profile

    def forget(self, key: str) -> None:
        self._mapping.pop(key, None)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._mapping, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> MonitorProfiles:
        """A missing or corrupt file just means nothing is remembered yet."""
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        return cls({str(k): str(v) for k, v in raw.items()})
