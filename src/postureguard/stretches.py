"""Stretch routines, matched to the fault the user actually commits.

A generic "take a break" reminder is easy to ignore because it is not about anything.
A routine that opens with "you have spent 41 minutes in forward head today" is about
something. So exercises are indexed by fault kind and the break timer picks from the
day's dominant fault rather than from a rotation.

Each exercise is described in plain movement language. No held claims about outcomes —
these are mobility drills, not treatment.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .rules import FaultKind


@dataclass(frozen=True)
class Exercise:
    name: str
    #: What it counteracts, in the user's terms.
    purpose: str
    seconds: int
    steps: tuple[str, ...]
    #: Fault this routine answers. None means it suits any break.
    targets: FaultKind | None = None


CHIN_TUCK = Exercise(
    name="Chin tuck",
    purpose="Resets the head over the shoulders after craning at the screen.",
    seconds=40,
    targets=FaultKind.FORWARD_HEAD,
    steps=(
        "Sit tall and look straight ahead.",
        "Draw your chin straight back, as if making a double chin. Don't tip your head down.",
        "Hold for 5 seconds, feeling a stretch at the base of the skull.",
        "Release slowly. Repeat 8 times.",
    ),
)

DOORWAY_OPENER = Exercise(
    name="Doorway chest opener",
    purpose="Opens the chest that rounds forward while you slouch.",
    seconds=60,
    targets=FaultKind.SPINE_FLEXION,
    steps=(
        "Stand in a doorway, forearms on the frame, elbows at shoulder height.",
        "Step through with one foot until you feel a stretch across the chest.",
        "Keep your ribs down and breathe out slowly.",
        "Hold 30 seconds, switch the leading foot, repeat.",
    ),
)

THORACIC_EXTENSION = Exercise(
    name="Seated thoracic extension",
    purpose="Restores the upper-back extension that hours of sitting flatten out.",
    seconds=45,
    targets=FaultKind.SPINE_FLEXION,
    steps=(
        "Sit with your feet flat and hands behind your head.",
        "Lean back over the top edge of the chair, opening through the upper back.",
        "Keep the movement in your ribs, not your lower back.",
        "Hold 3 seconds, return. Repeat 8 times.",
    ),
)

LATERAL_NECK = Exercise(
    name="Lateral neck release",
    purpose="Evens out the side you have been leaning onto.",
    seconds=50,
    targets=FaultKind.LATERAL_TILT,
    steps=(
        "Sit tall, let your right arm hang heavy.",
        "Tip your left ear toward your left shoulder without turning your head.",
        "Hold 20 seconds, breathing slowly.",
        "Switch sides and repeat.",
    ),
)

SHOULDER_BLADE_SQUEEZE = Exercise(
    name="Shoulder blade squeeze",
    purpose="Wakes up the muscles that hold your shoulders back.",
    seconds=40,
    targets=FaultKind.LATERAL_TILT,
    steps=(
        "Sit or stand tall with arms relaxed.",
        "Draw both shoulder blades down and together, as if holding a pencil between them.",
        "Hold 5 seconds without shrugging upward.",
        "Release. Repeat 10 times.",
    ),
)

TWENTY_TWENTY_TWENTY = Exercise(
    name="20-20-20 eye reset",
    purpose="Relieves the eye strain that pulls you toward the screen in the first place.",
    seconds=25,
    targets=FaultKind.SCREEN_TOO_CLOSE,
    steps=(
        "Look at something about 20 feet away.",
        "Hold your gaze there for 20 seconds.",
        "Blink deliberately a few times.",
        "Return to the screen and reset your seat distance.",
    ),
)

SEAT_DISTANCE_RESET = Exercise(
    name="Seat and screen reset",
    purpose="Corrects the too-far drift that has you leaning forward or squinting to compensate.",
    seconds=20,
    targets=FaultKind.SCREEN_TOO_FAR,
    steps=(
        "Sit all the way back so your hips touch the back of the chair.",
        "Scoot the chair in until your forearms rest comfortably on the desk.",
        "Check that the screen sits about an arm's length away, top at eye level.",
        "Settle your shoulders down and back before you continue.",
    ),
)

STAND_AND_WALK = Exercise(
    name="Stand and walk",
    purpose="The one thing that resets everything at once.",
    seconds=90,
    targets=None,
    steps=(
        "Stand up fully and let your arms hang.",
        "Walk for at least a minute — anywhere.",
        "Roll your shoulders back a few times as you go.",
        "Sit back down deliberately: hips to the back of the chair, feet flat.",
    ),
)

NECK_ROTATION = Exercise(
    name="Neck rotation release",
    purpose="Undoes the twist of holding your head turned toward a side monitor.",
    seconds=40,
    targets=FaultKind.HEAD_ROTATION,
    steps=(
        "Sit tall, facing forward.",
        "Slowly turn your head to look over one shoulder as far as is comfortable.",
        "Hold 10 seconds, feeling the stretch on the opposite side of the neck.",
        "Return to centre and repeat to the other side.",
    ),
)

SHOULDER_DROP = Exercise(
    name="Shoulder drop and roll",
    purpose="Releases the trapezius from holding your shoulders up near your ears.",
    seconds=40,
    targets=FaultKind.SHOULDER_SHRUG,
    steps=(
        "Sit or stand tall, arms relaxed at your sides.",
        "Inhale and shrug your shoulders up toward your ears.",
        "Exhale and let them drop heavily — do not ease them down, drop them.",
        "Roll them back and down a few times. Repeat 6 times.",
    ),
)

HIP_FLEXOR = Exercise(
    name="Standing hip flexor stretch",
    purpose="Releases the hips that shorten from sitting and drag your pelvis out of position.",
    seconds=60,
    targets=FaultKind.SPINE_FLEXION,
    steps=(
        "Step one foot well forward into a short lunge.",
        "Tuck your tailbone under and squeeze the back glute.",
        "Stand tall — you should feel the front of the back hip open.",
        "Hold 30 seconds each side.",
    ),
)


ALL_EXERCISES: tuple[Exercise, ...] = (
    CHIN_TUCK,
    DOORWAY_OPENER,
    THORACIC_EXTENSION,
    LATERAL_NECK,
    SHOULDER_BLADE_SQUEEZE,
    TWENTY_TWENTY_TWENTY,
    SEAT_DISTANCE_RESET,
    NECK_ROTATION,
    SHOULDER_DROP,
    HIP_FLEXOR,
    STAND_AND_WALK,
)


@dataclass(frozen=True)
class Routine:
    """A break's worth of exercises, and why these ones."""

    reason: str
    exercises: tuple[Exercise, ...] = field(default_factory=tuple)

    @property
    def seconds(self) -> int:
        return sum(exercise.seconds for exercise in self.exercises)


def exercises_for(fault: FaultKind | None) -> tuple[Exercise, ...]:
    return tuple(e for e in ALL_EXERCISES if e.targets is fault and fault is not None)


_REASONS = {
    FaultKind.FORWARD_HEAD: "Your head has been drifting forward of your shoulders.",
    FaultKind.SPINE_FLEXION: "You have been sinking and rounding through the upper back.",
    FaultKind.SCREEN_TOO_CLOSE: "You have been creeping toward the screen.",
    FaultKind.SCREEN_TOO_FAR: "You have been sitting well back from the screen.",
    FaultKind.LATERAL_TILT: "You have been leaning onto one side.",
    FaultKind.HEAD_ROTATION: "You have been holding your head turned to one side.",
    FaultKind.SHOULDER_SHRUG: "Your shoulders have been creeping up toward your ears.",
    FaultKind.DRIFT: "Your posture has been slowly degrading through the session.",
}


def routine_for(dominant: FaultKind | None) -> Routine:
    """Build a break routine around the day's most-committed fault.

    Always ends with standing up, whatever the fault — the targeted work is the point,
    but getting out of the chair is the part that reliably helps.
    """
    targeted = exercises_for(dominant)
    if not targeted:
        return Routine(
            reason="A regular break — nothing specific has been going wrong.",
            exercises=(TWENTY_TWENTY_TWENTY, STAND_AND_WALK),
        )
    return Routine(
        reason=_REASONS.get(dominant, "Time for a break."),
        exercises=(*targeted, STAND_AND_WALK),
    )


#: If the app has been closed longer than this, the accrued progress is treated as
#: stale rather than resumed. A quick relaunch — a crash, a quick Windows Update
#: restart — should not cost banked progress; anything longer means the user has
#: clearly been away, and resuming a countdown from before that gap would credit
#: time they were not at the desk for.
BREAK_STATE_STALE_AFTER_SECONDS = 30 * 60


class BreakTimer:
    """Counts working time toward the next break.

    Time only accrues while the user is actually present. A timer that keeps counting
    through lunch greets them with a break prompt the moment they sit down, which
    teaches them to dismiss it on sight.
    """

    def __init__(self, interval_minutes: float = 40.0, enabled: bool = True) -> None:
        self.interval_seconds = interval_minutes * 60.0
        self.enabled = enabled
        self._worked = 0.0
        self._last_tick: float | None = None
        self._due = False

    # --- persistence ----------------------------------------------------------
    #
    # `_last_tick` is a `time.monotonic()` value and is deliberately never persisted —
    # that clock is only meaningful within one process's lifetime, not across a
    # restart. Only `_worked` (a duration) and a wall-clock save time travel to disk;
    # the first `update()` call after restore re-establishes `_last_tick` exactly as
    # it does on a fresh timer.

    def to_state(self) -> dict:
        return {"worked_seconds": self._worked, "saved_at": time.time()}

    @classmethod
    def restore(
        cls,
        state: dict,
        interval_minutes: float,
        enabled: bool,
        now_wall: float | None = None,
    ) -> BreakTimer:
        timer = cls(interval_minutes, enabled)
        saved_at = state.get("saved_at")
        worked = state.get("worked_seconds")
        if not isinstance(saved_at, (int, float)) or not isinstance(worked, (int, float)):
            return timer
        now_wall = time.time() if now_wall is None else now_wall
        gap = now_wall - saved_at
        if 0 <= gap <= BREAK_STATE_STALE_AFTER_SECONDS:
            timer._worked = max(worked, 0.0)
        return timer

    def save_state(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_state()), encoding="utf-8")

    @classmethod
    def load_restored(
        cls, path: Path, interval_minutes: float, enabled: bool
    ) -> BreakTimer:
        """The usual construction path: pick up where a previous run left off,
        unless it left off long enough ago that doing so would be misleading."""
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(interval_minutes, enabled)
        if not isinstance(state, dict):
            return cls(interval_minutes, enabled)
        return cls.restore(state, interval_minutes, enabled)

    def update(self, present: bool, now: float) -> bool:
        """Advance the timer. Returns True on the frame a break becomes due."""
        previous, self._last_tick = self._last_tick, now
        if not self.enabled or not present or previous is None:
            return False

        delta = now - previous
        # A large gap means the app was asleep or the user was away; don't bank it.
        if delta <= 0 or delta > 5.0:
            return False

        self._worked += delta
        if self._worked >= self.interval_seconds and not self._due:
            self._due = True
            return True
        return False

    @property
    def due(self) -> bool:
        return self._due

    @property
    def seconds_until_due(self) -> float:
        return max(self.interval_seconds - self._worked, 0.0)

    @property
    def worked_seconds(self) -> float:
        return self._worked

    def taken(self) -> None:
        """The user took the break — start the next interval."""
        self._worked = 0.0
        self._due = False

    def postpone(self, minutes: float = 10.0) -> None:
        self._worked = max(self.interval_seconds - minutes * 60.0, 0.0)
        self._due = False
