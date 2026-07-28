"""The intervention ladder.

The overlay cue is always on and costs nothing to ignore, which is precisely why it
gets ignored. Escalation exists so that ignoring a fault has a rising cost — but the
rise has to be earned, or the app becomes something the user disables by Wednesday.

Two rules keep it honest:

**Time is only counted while the fault is continuously present.** Fix your posture and
the ladder resets to the bottom. The clock measures how long you have been ignoring the
correction, not how long the app has been running.

**Escalation never repeats without a cooldown.** Slipping, correcting, and slipping
again within a few seconds is one lapse, not two, and must not produce two toasts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Sequence

from .rules import Fault, FaultKind


class Level(IntEnum):
    """Rungs of the ladder. Ordered, so comparisons read naturally."""

    NONE = 0
    #: Overlay cue only — always active whenever a fault is present.
    CUE = 1
    #: A desktop notification naming the fault and the correction.
    TOAST = 2
    #: Progressive screen dimming until posture is corrected.
    DIM = 3


@dataclass(frozen=True)
class Intervention:
    level: Level
    fault: Fault | None
    #: 0-1, how far into the dim ramp. Only meaningful at Level.DIM.
    dim_progress: float = 0.0
    #: True on the frame a toast should actually be shown.
    toast_now: bool = False
    #: How long the current fault has gone uncorrected. Zero when posture is fine.
    held_seconds: float = 0.0


class Escalator:
    def __init__(
        self,
        toast_after_seconds: float = 25.0,
        dim_after_seconds: float = 60.0,
        dim_ramp_seconds: float = 20.0,
        cooldown_seconds: float = 45.0,
        alerts_enabled: bool = True,
        dim_enabled: bool = True,
    ) -> None:
        self.toast_after_seconds = toast_after_seconds
        self.dim_after_seconds = dim_after_seconds
        self.dim_ramp_seconds = dim_ramp_seconds
        self.cooldown_seconds = cooldown_seconds
        self.alerts_enabled = alerts_enabled
        self.dim_enabled = dim_enabled

        self._fault_since: float | None = None
        self._last_toast_at: float | None = None
        self._toasted_this_episode = False
        self._suppressed_until = 0.0

    # --- control ------------------------------------------------------------------

    def suppress(self, seconds: float, now: float) -> None:
        """Silence escalation for a while — the user asked for quiet."""
        self._suppressed_until = now + seconds
        self._reset_episode()

    def is_suppressed(self, now: float) -> bool:
        return now < self._suppressed_until

    def reset(self) -> None:
        self._reset_episode()
        self._last_toast_at = None

    def _reset_episode(self) -> None:
        self._fault_since = None
        self._toasted_this_episode = False

    # --- per-frame ----------------------------------------------------------------

    def update(
        self, faults: Sequence[Fault], now: float, *, fullscreen_active: bool = False
    ) -> Intervention:
        # Drift is a summary of the last ten minutes, not something to dim the screen
        # over. It gets a cue and nothing more.
        actionable = [f for f in faults if f.kind is not FaultKind.DRIFT]

        if not actionable:
            self._reset_episode()
            return Intervention(level=Level.NONE, fault=None)

        primary = actionable[0]

        if self._fault_since is None:
            self._fault_since = now
        held_for = now - self._fault_since

        if self.is_suppressed(now) or not self.alerts_enabled or fullscreen_active:
            return Intervention(level=Level.CUE, fault=primary, held_seconds=held_for)

        if held_for < self.toast_after_seconds:
            return Intervention(level=Level.CUE, fault=primary, held_seconds=held_for)

        toast_now = False
        if not self._toasted_this_episode:
            cooled = (
                self._last_toast_at is None
                or now - self._last_toast_at >= self.cooldown_seconds
            )
            if cooled:
                toast_now = True
                self._last_toast_at = now
            # Marked either way: a fault that came due during the cooldown has had its
            # turn, and must not fire the instant the cooldown lapses.
            self._toasted_this_episode = True

        if not self.dim_enabled or held_for < self.dim_after_seconds:
            return Intervention(
                level=Level.TOAST, fault=primary, toast_now=toast_now, held_seconds=held_for
            )

        # Ramp in rather than snapping to full dim — an abrupt darkening reads as a
        # fault in the machine, not a prompt to sit up.
        progress = min((held_for - self.dim_after_seconds) / max(self.dim_ramp_seconds, 0.1), 1.0)
        return Intervention(
            level=Level.DIM, fault=primary, dim_progress=progress,
            toast_now=toast_now, held_seconds=held_for,
        )
