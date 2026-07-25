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

from .. import paths, power
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

#: Smooth video needs the fast rate; a correction is legible at a far slower one, and
#: posture does not change on 33ms timescales in the first place.
FRAME_INTERVAL_MS = 33
MINI_FRAME_INTERVAL_MS = 100
#: Applied on top of whichever base rate is already in effect.
BATTERY_INTERVAL_MULTIPLIER = 2
#: Idle/lock/battery state changes slowly; checking every frame would be wasted work.
ACTIVITY_CHECK_INTERVAL_MS = 2000


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
    #: False while the camera has stopped delivering frames. Distinct from "no
    #: subject": nothing is being watched at all, which the user needs told.
    camera_healthy: bool = True
    #: True while monitoring is intentionally paused — locked session or sustained
    #: inactivity — as opposed to camera_healthy being False, which means broken.
    paused: bool = False


class MonitorController(QObject):
    """The single frame loop."""

    updated = Signal(object)  # LiveState
    toast_requested = Signal(str, str)  # title, cue
    dim_changed = Signal(float)  # 0-1 progress
    break_due = Signal(object)  # Routine
    failed = Signal(str)
    baseline_captured = Signal()
    camera_health_changed = Signal(bool)
    paused_changed = Signal(bool)

    def __init__(self, config: Config, store: SessionStore) -> None:
        super().__init__()
        self.config = config
        self.store = store

        self.camera: Camera | None = None
        self.tracker: PoseTracker | None = None
        self.engine: Engine | None = None
        self.escalator = self._build_escalator()
        # Pick up where a previous run left off, unless it left off long enough ago
        # that resuming the countdown would credit time the user was not at the desk.
        self.breaks = BreakTimer.load_restored(
            paths.break_state_path(), config.break_interval_minutes, config.breaks_enabled
        )

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._started_at = 0.0
        self._running = False
        self._camera_healthy = True

        # Defaults to "not visible" so a start_minimized launch runs at the mini
        # rate from the first frame rather than briefly at full rate; the moment the
        # main window actually shows, its showEvent corrects this (see window.py).
        self._window_visible = False
        self._paused_for_activity = False
        self._activity_timer = QTimer(self)
        self._activity_timer.setInterval(ACTIVITY_CHECK_INTERVAL_MS)
        self._activity_timer.timeout.connect(self._evaluate_activity)

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
        self._paused_for_activity = False
        self._timer.start(self._current_interval())
        self._activity_timer.start()
        return True

    def stop(self) -> None:
        self._timer.stop()
        self._activity_timer.stop()
        self._running = False
        self._paused_for_activity = False
        # Best-effort: a crash loses at most the progress since the last clean stop,
        # never more, and never anything that would require running on every tick.
        self.breaks.save_state(paths.break_state_path())
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

        if camera_changed:
            # Not gated on self._running: if the previously configured camera never
            # opened at all (a stale/removed device saved from a prior session), the
            # controller comes up with _running still False, and picking a working
            # camera here is the user's only way to recover without restarting the
            # app. Requiring "already running" to attempt a restart meant that fix
            # silently did nothing.
            self.stop()
            self.start()
        else:
            # A changed idle/lock/battery-saver setting should take effect promptly
            # rather than waiting out the next 2s activity tick.
            self._apply_frame_rate()

    # --- visibility and power ------------------------------------------------------

    def set_window_visible(self, visible: bool) -> None:
        """Told by the app when the main window is shown or hidden.

        The frame rate only needs to be smooth for a window actually being watched
        frame by frame; the mini window's correction updates are legible at a far
        slower rate, since posture does not change on 33ms timescales in the first
        place.
        """
        if visible == self._window_visible:
            return
        self._window_visible = visible
        self._apply_frame_rate()

    def _current_interval(self) -> int:
        interval = FRAME_INTERVAL_MS if self._window_visible else MINI_FRAME_INTERVAL_MS
        if self.config.battery_saver and power.on_battery():
            interval *= BATTERY_INTERVAL_MULTIPLIER
        return interval

    def _apply_frame_rate(self) -> None:
        if not self._running or self._paused_for_activity:
            return  # the paused timer is stopped outright; resume() re-derives this
        self._timer.setInterval(self._current_interval())

    def _evaluate_activity(self) -> None:
        if not self._running or self.camera is None:
            return
        locked = self.config.pause_when_locked and power.session_locked()
        idle = (
            self.config.pause_after_idle_minutes > 0
            and power.idle_seconds() >= self.config.pause_after_idle_minutes * 60
        )
        should_pause = locked or idle

        if should_pause and not self._paused_for_activity:
            self._paused_for_activity = True
            self.camera.pause()
            self._timer.stop()
            # Whatever was on screen is no longer being observed. Nobody should be
            # dimmed, or have a fault held against them, for a posture that has
            # stopped being watched on purpose.
            self.escalator.reset()
            self.dim_changed.emit(0.0)
            log.info("Paused (%s)", "locked" if locked else "idle")
            self.updated.emit(self._paused_state())
            self.paused_changed.emit(True)
        elif not should_pause and self._paused_for_activity:
            self._paused_for_activity = False
            self.camera.resume()
            self._timer.start(self._current_interval())
            log.info("Resumed")
            self.paused_changed.emit(False)

    def _paused_state(self) -> LiveState:
        return LiveState(
            frame=None,
            reading=Reading(status="paused", message="Paused — no activity detected"),
            aspect=self.camera.aspect if self.camera else 4 / 3,
            session_seconds=time.monotonic() - self._started_at,
            seconds_until_break=self.breaks.seconds_until_due,
            camera_healthy=True,
            paused=True,
        )

    # --- frame loop ---------------------------------------------------------------

    def _tick(self) -> None:
        if self.camera is None or self.tracker is None or self.engine is None:
            return
        if self._paused_for_activity:
            return  # the timer is stopped during a pause; a defensive no-op if a
            # queued tick still lands right on the transition

        self._check_camera_health()

        frame = self.camera.read()
        if frame is None:
            # No frame at all. If the camera is merely warming up there is nothing to
            # report yet; if it has died the user is owed a state that says so rather
            # than a UI frozen on the last good frame.
            if not self._camera_healthy:
                self._emit_camera_lost()
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
                camera_healthy=True,
            )
        )

    def _check_camera_health(self) -> None:
        healthy = self.camera is not None and self.camera.healthy
        if healthy == self._camera_healthy:
            return
        self._camera_healthy = healthy
        self.camera_health_changed.emit(healthy)
        if not healthy:
            # Whatever was on screen is no longer true. Clear the escalation so the
            # user is not dimmed for a posture nobody can currently see.
            self.escalator.reset()
            self.dim_changed.emit(0.0)
            log.warning("Camera lost; monitoring paused until it returns")
        else:
            log.info("Camera recovered; monitoring resumed")

    def _emit_camera_lost(self) -> None:
        self.updated.emit(
            LiveState(
                frame=None,
                reading=Reading(status="camera_lost", message="Camera disconnected"),
                aspect=self.camera.aspect if self.camera else 4 / 3,
                session_seconds=time.monotonic() - self._started_at,
                seconds_until_break=self.breaks.seconds_until_due,
                camera_healthy=False,
            )
        )

    def _routine(self) -> Routine:
        return routine_for(self.store.dominant_fault(days=1))

    def current_routine(self) -> Routine:
        """The routine a break would offer right now."""
        return self._routine()

    def dominant_fault(self) -> FaultKind | None:
        return self.store.dominant_fault(days=7)
