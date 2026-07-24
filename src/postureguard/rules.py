"""Metrics plus baseline to named faults, with the flicker taken out.

Pure logic. The only state is the debounce/hysteresis bookkeeping in
:class:`RuleEngine`, which is driven entirely by the samples handed to ``update`` —
so a whole session can be replayed deterministically in a test.

Three ideas do most of the work here:

**Everything is relative to the user's own baseline.** Thresholds are fractional
deviations, not anatomical constants, so a tall person on a low camera and a short
person on a high one get the same treatment.

**Ambiguous evidence does not fire.** Forward head requires the ear-shoulder gap to
close *and* the face to grow. Pushing the chair back moves one; only real craning moves
both, because both are already normalized by shoulder width.

**Alerts need sustained evidence and are sticky once raised.** A fault must hold for
``enter_frames`` before it exists, and once raised it only clears when the signal falls
well below where it entered. Without both, the user gets a strobe light at the threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from .calibration import Baseline
from .metrics import PostureMetrics


class FaultKind(str, Enum):
    FORWARD_HEAD = "forward_head"
    SPINE_FLEXION = "spine_flexion"
    SCREEN_TOO_CLOSE = "screen_too_close"
    LATERAL_TILT = "lateral_tilt"
    DRIFT = "drift"


@dataclass(frozen=True)
class Fault:
    """A detected posture problem, and what to do about it."""

    kind: FaultKind
    #: How far past threshold, where 1.0 is exactly at it. Drives escalation urgency.
    severity: float
    #: Plain instruction for the correction — the difference between nagging and helping.
    cue: str
    #: Landmarks the overlay should paint red.
    joints: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        return FAULT_TITLES[self.kind]


FAULT_TITLES: dict[FaultKind, str] = {
    FaultKind.FORWARD_HEAD: "Forward head",
    FaultKind.SPINE_FLEXION: "Slouching",
    FaultKind.SCREEN_TOO_CLOSE: "Too close to the screen",
    FaultKind.LATERAL_TILT: "Leaning to one side",
    FaultKind.DRIFT: "Posture drifting",
}

_CUES: dict[FaultKind, str] = {
    FaultKind.FORWARD_HEAD: "Pull your chin straight back and stack your ears over your shoulders.",
    FaultKind.SPINE_FLEXION: "Sit tall — lift your chest and stack your ribs over your hips.",
    FaultKind.SCREEN_TOO_CLOSE: "Push back to about an arm's length from the screen.",
    FaultKind.LATERAL_TILT: "Level out — even your shoulders and bring your head upright.",
    FaultKind.DRIFT: "You've been slowly sinking. Reset: feet flat, hips back, chest up.",
}

_JOINTS: dict[FaultKind, tuple[str, ...]] = {
    FaultKind.FORWARD_HEAD: ("left_ear", "right_ear", "left_shoulder", "right_shoulder"),
    FaultKind.SPINE_FLEXION: ("left_shoulder", "right_shoulder", "left_hip", "right_hip"),
    FaultKind.SCREEN_TOO_CLOSE: ("left_eye", "right_eye", "nose"),
    FaultKind.LATERAL_TILT: ("left_shoulder", "right_shoulder", "left_eye", "right_eye"),
    FaultKind.DRIFT: ("left_shoulder", "right_shoulder"),
}


@dataclass(frozen=True)
class Thresholds:
    """Tuning knobs. Defaults are deliberately forgiving — a tool that cries wolf
    gets muted, and a muted tool corrects nothing."""

    #: Fraction the ear-shoulder gap must close, relative to baseline.
    forward_head_gap_drop: float = 0.15
    #: Fraction the face must grow, relative to baseline. Both are required.
    forward_head_face_rise: float = 0.06
    #: Fraction the inter-ocular distance must grow before "too close".
    screen_close_rise: float = 0.15
    #: Degrees of head or shoulder roll away from baseline.
    tilt_degrees: float = 9.0
    #: Degrees of torso lean away from baseline.
    torso_degrees: float = 12.0
    #: Frame-height units the shoulders may sink before it counts as collapsing.
    sink_units: float = 0.045

    #: Consecutive frames over threshold before a fault is raised.
    enter_frames: int = 15
    #: Consecutive frames under the exit threshold before it is dropped.
    exit_frames: int = 5
    #: A raised fault clears only below this fraction of its entry threshold.
    exit_ratio: float = 0.8

    #: Drift compares a 10-minute median, where even small deviations are meaningful,
    #: so it trips at a fraction of the instantaneous thresholds.
    drift_scale: float = 0.6


class _FaultState:
    """Debounce and hysteresis for one fault kind."""

    def __init__(self) -> None:
        self.active = False
        self.severity = 0.0
        self._over = 0
        self._under = 0

    def update(self, excess: float | None, thresholds: Thresholds) -> bool:
        # No measurement is not evidence of good posture, but it is not evidence of
        # bad posture either — treat it as clean so faults release when the user
        # leaves rather than latching on forever.
        value = 0.0 if excess is None else excess

        if not self.active:
            if value >= 1.0:
                self._over += 1
                self._under = 0
                if self._over >= thresholds.enter_frames:
                    self.active = True
                    self.severity = value
            else:
                # Strict reset: a brief lapse must never accumulate into an alert.
                self._over = 0
            return self.active

        self.severity = max(value, 1.0)
        if value < thresholds.exit_ratio:
            self._under += 1
            if self._under >= thresholds.exit_frames:
                self.active = False
                self.severity = 0.0
                self._over = 0
                self._under = 0
        else:
            self._under = 0
        return self.active


def _deviation_excess(
    value: float | None,
    reference: float | None,
    threshold: float,
    *,
    direction: int = 0,
) -> float | None:
    """How far past ``threshold`` the absolute deviation is, as a multiple.

    ``direction`` of +1 counts only increases, -1 only decreases, 0 either way.
    """
    if value is None or reference is None or threshold <= 0:
        return None
    delta = value - reference
    if direction > 0:
        delta = max(delta, 0.0)
    elif direction < 0:
        delta = max(-delta, 0.0)
    else:
        delta = abs(delta)
    return delta / threshold


def _relative_excess(
    value: float | None,
    reference: float | None,
    threshold: float,
    *,
    rising: bool,
) -> float | None:
    """Same idea, but as a fraction of the baseline — scale-invariant."""
    if value is None or reference is None or threshold <= 0 or reference == 0:
        return None
    change = (value - reference) / abs(reference)
    if not rising:
        change = -change
    return max(change, 0.0) / threshold


def _forward_head(metrics: PostureMetrics, base: Baseline, t: Thresholds) -> float | None:
    """Craning requires both signals; either alone is just distance change."""
    gap = _relative_excess(
        metrics.head_shoulder_gap, base.get("head_shoulder_gap"),
        t.forward_head_gap_drop, rising=False,
    )
    face = _relative_excess(
        metrics.face_scale, base.get("face_scale"),
        t.forward_head_face_rise, rising=True,
    )
    if gap is None or face is None:
        return None
    # min() is the AND: the weaker of the two signals gates the fault.
    return min(gap, face)


def _spine_flexion(metrics: PostureMetrics, base: Baseline, t: Thresholds) -> float | None:
    """Sinking in the frame, or a visibly tilted torso when the hips are in view."""
    sink = _deviation_excess(
        metrics.shoulder_height, base.get("shoulder_height"), t.sink_units, direction=+1
    )
    torso = _deviation_excess(metrics.torso_angle, base.get("torso_angle"), t.torso_degrees)
    candidates = [c for c in (sink, torso) if c is not None]
    return max(candidates) if candidates else None


def _screen_too_close(metrics: PostureMetrics, base: Baseline, t: Thresholds) -> float | None:
    # Only closer is a problem; sitting further back is not a posture fault.
    return _relative_excess(
        metrics.screen_distance, base.get("screen_distance"), t.screen_close_rise, rising=True
    )


def _lateral_tilt(metrics: PostureMetrics, base: Baseline, t: Thresholds) -> float | None:
    eye = _deviation_excess(metrics.eye_roll, base.get("eye_roll"), t.tilt_degrees)
    shoulder = _deviation_excess(metrics.shoulder_roll, base.get("shoulder_roll"), t.tilt_degrees)
    candidates = [c for c in (eye, shoulder) if c is not None]
    return max(candidates) if candidates else None


_CHECKS = {
    FaultKind.FORWARD_HEAD: _forward_head,
    FaultKind.SPINE_FLEXION: _spine_flexion,
    FaultKind.SCREEN_TOO_CLOSE: _screen_too_close,
    FaultKind.LATERAL_TILT: _lateral_tilt,
}


@dataclass
class RuleEngine:
    """Turns a stream of metrics into a stable stream of faults."""

    baseline: Baseline
    thresholds: Thresholds = field(default_factory=Thresholds)
    _states: dict[FaultKind, _FaultState] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self._states = {kind: _FaultState() for kind in _CHECKS}

    def update(self, metrics: PostureMetrics) -> list[Fault]:
        """Feed one frame. Returns the currently raised faults, worst first."""
        faults: list[Fault] = []
        for kind, check in _CHECKS.items():
            state = self._states[kind]
            if state.update(check(metrics, self.baseline, self.thresholds), self.thresholds):
                faults.append(
                    Fault(
                        kind=kind,
                        severity=state.severity,
                        cue=_CUES[kind],
                        joints=_JOINTS[kind],
                    )
                )
        faults.sort(key=lambda f: f.severity, reverse=True)
        return faults

    @property
    def active(self) -> frozenset[FaultKind]:
        return frozenset(k for k, s in self._states.items() if s.active)

    def reset(self) -> None:
        """Drop all fault state — after recalibration or a snooze expiring."""
        for state in self._states.values():
            state.__init__()  # type: ignore[misc]


def evaluate_drift(
    baseline: Baseline,
    rolling_medians: Mapping[str, float],
    thresholds: Thresholds,
) -> Fault | None:
    """Compare a long rolling median against the baseline.

    This is what catches the afternoon slide. Each individual frame may sit well inside
    every instantaneous threshold while the *typical* posture has quietly degraded, and
    only an aggregate over many minutes can see that.
    """
    if not rolling_medians:
        return None

    scaled = Thresholds(
        forward_head_gap_drop=thresholds.forward_head_gap_drop * thresholds.drift_scale,
        forward_head_face_rise=thresholds.forward_head_face_rise * thresholds.drift_scale,
        screen_close_rise=thresholds.screen_close_rise * thresholds.drift_scale,
        tilt_degrees=thresholds.tilt_degrees * thresholds.drift_scale,
        torso_degrees=thresholds.torso_degrees * thresholds.drift_scale,
        sink_units=thresholds.sink_units * thresholds.drift_scale,
    )
    median_metrics = PostureMetrics(
        **{
            name: rolling_medians.get(name)
            for name in PostureMetrics().as_dict()
        }
    )

    worst = 0.0
    for check in _CHECKS.values():
        excess = check(median_metrics, baseline, scaled)
        if excess is not None:
            worst = max(worst, excess)

    if worst < 1.0:
        return None
    return Fault(
        kind=FaultKind.DRIFT,
        severity=worst,
        cue=_CUES[FaultKind.DRIFT],
        joints=_JOINTS[FaultKind.DRIFT],
    )
