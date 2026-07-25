"""The session state machine: calibrate, then monitor.

Takes detected landmarks in and produces a :class:`Reading` out. Deliberately free of
Qt and OpenCV — the camera and the window are the caller's problem — so an entire
session, calibration included, can be replayed frame by frame in a test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .calibration import Baseline, BaselineBuilder, DriftTracker
from .landmarks import Landmarks
from .metrics import PostureMetrics, compute_metrics
from .rules import Fault, FaultKind, RuleEngine, Thresholds, evaluate_drift


class Phase(str, Enum):
    PREPARING = "preparing"
    CAPTURING = "capturing"
    MONITORING = "monitoring"


#: Seconds of "get ready" before the baseline recording starts.
PREP_SECONDS = 4.0
#: Seconds of good posture recorded into the baseline.
CAPTURE_SECONDS = 5.0
#: Drift is re-checked on this cadence rather than every frame; it moves slowly and
#: the median is not cheap.
DRIFT_INTERVAL_SECONDS = 20.0
#: How long the subject may vanish mid-calibration before the countdown restarts.
#: Pose detection drops the odd frame on a live camera — blinking, a hand crossing the
#: torso, a motion-blurred turn. Restarting on the first missed frame means calibration
#: never finishes in practice, so brief gaps are tolerated and only a sustained absence
#: counts as the user having left.
CALIBRATION_GRACE_SECONDS = 1.0


@dataclass
class Reading:
    """One processed frame."""

    landmarks: Landmarks | None = None
    metrics: PostureMetrics = field(default_factory=PostureMetrics)
    faults: list[Fault] = field(default_factory=list)
    status: str = "starting"
    message: str = ""
    baseline: Baseline | None = None
    #: True on the frame calibration completes, so the caller can persist it.
    baseline_just_captured: bool = False


class Engine:
    def __init__(
        self,
        baseline: Baseline | None = None,
        thresholds: Thresholds | None = None,
        prep_seconds: float = PREP_SECONDS,
        capture_seconds: float = CAPTURE_SECONDS,
    ) -> None:
        self.thresholds = thresholds or Thresholds()
        self.baseline = baseline
        self.prep_seconds = prep_seconds
        self.capture_seconds = capture_seconds

        self._rules = RuleEngine(baseline, self.thresholds) if baseline else None
        self._drift = DriftTracker()
        self._drift_fault: Fault | None = None
        self._last_drift_check = 0.0

        self._builder = BaselineBuilder()
        self._phase = Phase.MONITORING if baseline else Phase.PREPARING
        self._phase_started: float | None = None
        self._last_seen: float | None = None
        self.snoozed_until = 0.0

    # --- control ------------------------------------------------------------------

    @property
    def phase(self) -> Phase:
        return self._phase

    def recalibrate(self) -> None:
        """Throw away the current baseline and start over.

        Needed whenever the camera or chair moves: the absolute metrics are only
        comparable against a baseline captured from the same viewpoint.
        """
        self._builder = BaselineBuilder()
        self._phase = Phase.PREPARING
        self._phase_started = None
        self._last_seen = None
        self._drift.reset()
        self._drift_fault = None

    def snooze(self, seconds: float, now: float) -> None:
        self.snoozed_until = now + seconds
        if self._rules is not None:
            self._rules.reset()

    def is_snoozed(self, now: float) -> bool:
        return now < self.snoozed_until

    # --- per-frame ----------------------------------------------------------------

    def process(self, landmarks: Landmarks | None, aspect: float, now: float) -> Reading:
        metrics = (
            compute_metrics(landmarks, aspect) if landmarks is not None else PostureMetrics()
        )
        if self._phase is Phase.MONITORING:
            return self._monitor(landmarks, metrics, now)
        return self._calibrate(landmarks, metrics, now)

    # --- calibration --------------------------------------------------------------

    def _calibrate(
        self, landmarks: Landmarks | None, metrics: PostureMetrics, now: float
    ) -> Reading:
        if self._phase_started is None:
            self._phase_started = now

        if metrics.any_available():
            self._last_seen = now
        else:
            # Don't run the countdown against an empty chair — it would bank a
            # baseline of nothing and hand the user a broken reference. But a single
            # dropped detection is not an empty chair, so only a sustained absence
            # restarts things.
            missing_for = now - self._last_seen if self._last_seen is not None else None
            if missing_for is not None and missing_for <= CALIBRATION_GRACE_SECONDS:
                return Reading(
                    landmarks=landmarks,
                    metrics=metrics,
                    status="calibrating",
                    message="Hold still…",
                )
            self._builder = BaselineBuilder()
            self._phase = Phase.PREPARING
            self._phase_started = now
            self._last_seen = None
            return Reading(
                landmarks=landmarks,
                metrics=metrics,
                status="calibrating",
                message="Step into view to calibrate",
            )

        elapsed = now - self._phase_started

        if self._phase is Phase.PREPARING:
            remaining = max(self.prep_seconds - elapsed, 0.0)
            if remaining <= 0:
                self._phase = Phase.CAPTURING
                self._phase_started = now
                remaining = 0.0
            return Reading(
                landmarks=landmarks,
                metrics=metrics,
                status="calibrating",
                # Kept short so the countdown survives in the collapsed bar, where a
                # longer sentence elides away exactly the digit that matters.
                message=f"Sit tall — baseline in {remaining:.0f}",
            )

        self._builder.add(metrics)
        remaining = max(self.capture_seconds - elapsed, 0.0)
        if remaining <= 0 and self._builder.ready(minimum=1):
            self.baseline = self._builder.build(minimum=max(self._builder.frames // 2, 1))
            self._rules = RuleEngine(self.baseline, self.thresholds)
            self._phase = Phase.MONITORING
            self._phase_started = now
            return Reading(
                landmarks=landmarks,
                metrics=metrics,
                status="in_tolerance",
                message="Baseline captured. Now monitoring.",
                baseline=self.baseline,
                baseline_just_captured=True,
            )

        return Reading(
            landmarks=landmarks,
            metrics=metrics,
            status="calibrating",
            message=f"Hold it — {remaining:.0f}",
        )

    # --- monitoring ---------------------------------------------------------------

    def _monitor(
        self, landmarks: Landmarks | None, metrics: PostureMetrics, now: float
    ) -> Reading:
        assert self._rules is not None

        faults = self._rules.update(metrics)
        self._drift.add(metrics, now)

        if now - self._last_drift_check >= DRIFT_INTERVAL_SECONDS:
            self._last_drift_check = now
            self._drift_fault = evaluate_drift(
                self.baseline, self._drift.medians(), self.thresholds
            )
        if self._drift_fault is not None and not any(
            f.kind is FaultKind.DRIFT for f in faults
        ):
            faults = [*faults, self._drift_fault]

        # "No subject" is about whether anything was measurable, not about whether a
        # landmark object came back — a detection with every joint occluded tells us
        # exactly as much as no detection at all.
        present = metrics.any_available()

        if self.is_snoozed(now):
            status = "snoozed"
        elif not present:
            status = "searching"
        elif any(f.kind is not FaultKind.DRIFT for f in faults):
            status = "fault"
        elif faults:
            status = "drifting"
        else:
            status = "in_tolerance"

        return Reading(
            landmarks=landmarks,
            metrics=metrics,
            faults=faults,
            status=status,
            message="" if present else "Step into view",
            baseline=self.baseline,
        )
