"""Owns the live pipeline and broadcasts its output to whatever is listening.

Screens observe rather than drive. Only this object touches the camera, the pose model
and the engine, so there is exactly one frame loop no matter how many views are open —
and switching screens cannot restart the camera, lose the calibration, or double the
frame rate.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from .. import paths
from ..calibration import Baseline
from ..capture import Camera, CameraConfig, CameraError
from ..config import Config
from ..engine import Engine, Phase, Reading
from ..escalation import Escalator, Intervention, Level
from ..pose import ModelUnavailable, PoseTracker
from ..rules import FaultKind
from ..session import SessionStore
from ..stretches import BreakTimer, Routine, routine_for

log = logging.getLogger(__name__)

FRAME_INTERVAL_MS = 33


@dataclass
class LiveState:
    """One frame's worth of everything the UI might want to show."""

    frame: np.ndarray | None = None
    reading: Reading = field(default_factory=Reading)
    intervention: Intervention = field(
        default_factory=lambda: Intervention(level=Level.NONE, fault=None)
    )
    aspect: float = 4 / 3
    session_seconds: float = 0.0
    seconds_until_break: float = 0.0
    calibrating: bool = False


class MonitorController(QObject):
    """The single frame loop."""

    updated = Signal(object)  # LiveState
    toast_requested = Signal(str, str)  # title, cue
    dim_changed = Signal(float)  # 0-1 progress
    break_due = Signal(object)  # Routine
    failed = Signal(str)
    baseline_captured = Signal()

    def __init__(self, config: Config, store: SessionStore) -> None:
        super().__init__()
        self.config = config
        self.store = store

        self.camera: Camera | None = None
        self.tracker: PoseTracker | None = None
        self.engine: Engine | None = None
        self.escalator = self._build_escalator()
        self.breaks = BreakTimer(config.break_interval_minutes, config.breaks_enabled)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._started_at = 0.0
        self._running = False

    # --- lifecycle ----------------------------------------------------------------

    def _build_escalator(self) -> Escalator:
        return Escalator(
            toast_after_seconds=self.config.toast_after_seconds,
            dim_after_seconds=self.config.dim_after_seconds,
            alerts_enabled=self.config.alerts_enabled,
            dim_enabled=self.config.dim_enabled,
        )

    def start(self) -> bool:
        """Bring up camera, model and engine. Returns False and emits `failed` if not."""
        if self._running:
            return True
        try:
            self.tracker = PoseTracker()
        except ModelUnavailable as exc:
            self.failed.emit(str(exc))
            return False
        try:
            self.camera = Camera(
                CameraConfig(index=self.config.camera_index, mirror=self.config.mirror)
            ).start()
        except CameraError as exc:
            self.tracker.close()
            self.tracker = None
            self.failed.emit(str(exc))
            return False

        self.engine = Engine(
            Baseline.load(paths.baseline_path()), self.config.thresholds()
        )
        self._started_at = time.monotonic()
        self._running = True
        self._timer.start(FRAME_INTERVAL_MS)
        return True

    def stop(self) -> None:
        self._timer.stop()
        self._running = False
        if self.camera is not None:
            self.camera.stop()
            self.camera = None
        if self.tracker is not None:
            self.tracker.close()
            self.tracker = None
        self.dim_changed.emit(0.0)

    @property
    def running(self) -> bool:
        return self._running

    # --- user actions -------------------------------------------------------------

    def recalibrate(self) -> None:
        if self.engine is not None:
            self.engine.recalibrate()
            self.escalator.reset()

    def snooze(self, minutes: float | None = None) -> None:
        minutes = self.config.snooze_minutes if minutes is None else minutes
        now = time.monotonic()
        if self.engine is not None:
            self.engine.snooze(minutes * 60, now)
        self.escalator.suppress(minutes * 60, now)
        self.dim_changed.emit(0.0)

    def apply_config(self, config: Config) -> None:
        """Adopt changed settings without dropping the session.

        Restarting the camera on a slider drag would cost the user their calibration
        and several seconds of blank screen, so only the pieces that actually depend
        on a changed value are rebuilt.
        """
        camera_changed = (
            config.camera_index != self.config.camera_index
            or config.mirror != self.config.mirror
        )
        self.config = config
        self.escalator = self._build_escalator()
        self.breaks.enabled = config.breaks_enabled
        self.breaks.interval_seconds = config.break_interval_minutes * 60.0
        if self.engine is not None:
            self.engine.thresholds = config.thresholds()

        if camera_changed and self._running:
            self.stop()
            self.start()

    # --- frame loop ---------------------------------------------------------------

    def _tick(self) -> None:
        if self.camera is None or self.tracker is None or self.engine is None:
            return

        frame = self.camera.read()
        if frame is None:
            return

        now = time.monotonic()
        aspect = self.camera.aspect
        landmarks = self.tracker.detect(frame, int(now * 1000))
        reading = self.engine.process(landmarks, aspect, now)

        if reading.baseline_just_captured and reading.baseline is not None:
            reading.baseline.save(paths.baseline_path())
            self.baseline_captured.emit()
            log.info("Baseline saved to %s", paths.baseline_path())

        intervention = self.escalator.update(reading.faults, now)
        if intervention.toast_now and intervention.fault is not None:
            self.toast_requested.emit(intervention.fault.title, intervention.fault.cue)
        self.dim_changed.emit(
            intervention.dim_progress if intervention.level is Level.DIM else 0.0
        )

        present = reading.metrics.any_available()
        if self.engine.phase is Phase.MONITORING:
            self.store.log(reading.status, reading.faults)
            if self.breaks.update(present, now):
                self.break_due.emit(self._routine())

        self.updated.emit(
            LiveState(
                frame=frame,
                reading=reading,
                intervention=intervention,
                aspect=aspect,
                session_seconds=now - self._started_at,
                seconds_until_break=self.breaks.seconds_until_due,
                calibrating=self.engine.phase is not Phase.MONITORING,
            )
        )

    def _routine(self) -> Routine:
        return routine_for(self.store.dominant_fault(days=1))

    def current_routine(self) -> Routine:
        """The routine a break would offer right now."""
        return self._routine()

    def dominant_fault(self) -> FaultKind | None:
        return self.store.dominant_fault(days=7)
