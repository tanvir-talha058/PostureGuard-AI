"""Controller behaviour around camera health.

The pipeline is driven with stand-in camera/tracker/engine objects, so a lost camera
can be simulated without unplugging one.
"""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from postureguard.config import Config  # noqa: E402
from postureguard.engine import Engine  # noqa: E402
from postureguard.session import SessionStore  # noqa: E402
from postureguard.ui.controller import MonitorController  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    yield QApplication.instance() or QApplication([])


class FakeCamera:
    """A camera that can be told to fail, or to pause."""

    def __init__(self) -> None:
        self.healthy = True
        self.paused = False
        self.aspect = 4 / 3
        self._frame = np.zeros((48, 64, 3), dtype=np.uint8)

    def read(self):
        if self.paused:
            return None
        return self._frame if self.healthy else None

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def stop(self) -> None:
        pass


class FakeTracker:
    def detect(self, frame, timestamp_ms):
        return None  # nobody in view; enough to exercise the health path

    def close(self) -> None:
        pass


def controller(qt_app) -> MonitorController:
    control = MonitorController(Config(), SessionStore())
    control.camera = FakeCamera()
    control.tracker = FakeTracker()
    control.engine = Engine(thresholds=Config().thresholds())
    return control


class TestCameraHealth:
    def test_a_healthy_camera_reports_nothing(self, qt_app):
        control = controller(qt_app)
        changes = []
        control.camera_health_changed.connect(changes.append)
        for _ in range(5):
            control._tick()
        assert changes == []

    def test_losing_the_camera_is_announced_once(self, qt_app):
        control = controller(qt_app)
        changes = []
        control.camera_health_changed.connect(changes.append)

        control.camera.healthy = False
        for _ in range(5):
            control._tick()

        assert changes == [False], "a lost camera must be reported once, not per frame"

    def test_recovery_is_announced(self, qt_app):
        control = controller(qt_app)
        changes = []
        control.camera_health_changed.connect(changes.append)

        control.camera.healthy = False
        control._tick()
        control.camera.healthy = True
        control._tick()

        assert changes == [False, True]

    def test_a_lost_camera_still_emits_state_for_the_ui(self, qt_app):
        """Otherwise the UI freezes on the last good frame and looks live."""
        control = controller(qt_app)
        states = []
        control.updated.connect(states.append)

        control.camera.healthy = False
        control._tick()

        assert states, "the UI must be told, not left showing stale data"
        assert states[-1].camera_healthy is False
        assert states[-1].frame is None
        assert states[-1].reading.status == "camera_lost"

    def test_losing_the_camera_clears_any_screen_dimming(self, qt_app):
        """Nobody should be dimmed for a posture that can no longer be observed."""
        control = controller(qt_app)
        dims = []
        control.dim_changed.connect(dims.append)

        control.camera.healthy = False
        control._tick()

        assert dims and dims[-1] == 0.0

    def test_a_lost_camera_is_not_logged_as_time_at_the_desk(self, qt_app):
        control = controller(qt_app)
        control.camera.healthy = False
        for _ in range(5):
            control._tick()
        assert control.store.today().tracked_seconds == 0


class TestFrameRate:
    def test_defaults_to_the_mini_rate_before_any_window_is_shown(self, qt_app, monkeypatch):
        """A start_minimized launch should run at the low rate from frame one, not
        briefly at full rate until something happens to correct it."""
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "on_battery", lambda: False)
        control = controller(qt_app)
        assert control._current_interval() == controller_module.MINI_FRAME_INTERVAL_MS

    def test_showing_the_window_switches_to_the_full_rate(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "on_battery", lambda: False)
        control = controller(qt_app)
        control._running = True
        control.set_window_visible(True)
        assert control._timer.interval() == controller_module.FRAME_INTERVAL_MS

    def test_hiding_the_window_returns_to_the_mini_rate(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "on_battery", lambda: False)
        control = controller(qt_app)
        control._running = True
        control.set_window_visible(True)
        control.set_window_visible(False)
        assert control._timer.interval() == controller_module.MINI_FRAME_INTERVAL_MS

    def test_battery_saver_slows_whichever_rate_is_active(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "on_battery", lambda: True)
        control = controller(qt_app)
        control.config.battery_saver = True
        control._running = True
        control.set_window_visible(True)
        assert control._timer.interval() == (
            controller_module.FRAME_INTERVAL_MS * controller_module.BATTERY_INTERVAL_MULTIPLIER
        )

    def test_battery_saver_disabled_keeps_the_normal_rate_on_battery(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "on_battery", lambda: True)
        control = controller(qt_app)
        control.config.battery_saver = False
        control._running = True
        control.set_window_visible(True)
        assert control._timer.interval() == controller_module.FRAME_INTERVAL_MS


class TestSnoozeBackoff:
    @pytest.fixture
    def isolated_home(self, tmp_path, monkeypatch):
        # SnoozeBackoff persists to paths.snooze_backoff_path(); route it to a
        # scratch dir so this test can never touch the real user's app data.
        monkeypatch.setenv("POSTUREGUARD_HOME", str(tmp_path))
        return tmp_path

    def test_emits_after_the_threshold_number_of_snoozes(self, qt_app, isolated_home):
        from postureguard.backoff import SNOOZE_THRESHOLD

        control = controller(qt_app)
        control._running = True
        emitted = []
        control.sensitivity_backed_off.connect(emitted.append)

        for _ in range(SNOOZE_THRESHOLD - 1):
            control.snooze()
        assert emitted == []
        control.snooze()
        assert len(emitted) == 1
        assert emitted[0] < control.config.sensitivity

    def test_disabled_in_config_never_emits(self, qt_app, isolated_home):
        from postureguard.backoff import SNOOZE_THRESHOLD

        control = controller(qt_app)
        control._running = True
        control.config.auto_backoff_enabled = False
        emitted = []
        control.sensitivity_backed_off.connect(emitted.append)

        for _ in range(SNOOZE_THRESHOLD + 2):
            control.snooze()
        assert emitted == []


class TestFullscreenSuppression:
    def _control(self, qt_app):
        control = controller(qt_app)
        control._running = True
        return control

    def test_a_fullscreen_foreground_window_is_flagged(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "session_locked", lambda: False)
        monkeypatch.setattr(controller_module.power, "idle_seconds", lambda: 0.0)
        monkeypatch.setattr(controller_module.presentation, "foreground_is_fullscreen", lambda: True)
        control = self._control(qt_app)

        control._evaluate_activity()

        assert control._fullscreen_active is True

    def test_disabled_in_config_never_checks_the_platform(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "session_locked", lambda: False)
        monkeypatch.setattr(controller_module.power, "idle_seconds", lambda: 0.0)
        monkeypatch.setattr(controller_module.presentation, "foreground_is_fullscreen", lambda: True)
        control = self._control(qt_app)
        control.config.suppress_when_fullscreen = False

        control._evaluate_activity()

        assert control._fullscreen_active is False


class TestActivityPause:
    def _control(self, qt_app):
        control = controller(qt_app)
        control._running = True
        return control

    def test_a_locked_session_pauses_the_camera(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "session_locked", lambda: True)
        monkeypatch.setattr(controller_module.power, "idle_seconds", lambda: 0.0)
        control = self._control(qt_app)

        control._evaluate_activity()

        assert control.camera.paused
        assert control._paused_for_activity
        assert not control._timer.isActive()

    def test_sustained_idleness_pauses_the_camera(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "session_locked", lambda: False)
        monkeypatch.setattr(controller_module.power, "idle_seconds", lambda: 999.0)
        control = self._control(qt_app)
        control.config.pause_after_idle_minutes = 1

        control._evaluate_activity()

        assert control.camera.paused

    def test_idle_pause_can_be_disabled(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "session_locked", lambda: False)
        monkeypatch.setattr(controller_module.power, "idle_seconds", lambda: 999.0)
        control = self._control(qt_app)
        control.config.pause_after_idle_minutes = 0

        control._evaluate_activity()

        assert not control.camera.paused

    def test_pausing_is_announced_once_not_every_check(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "session_locked", lambda: True)
        monkeypatch.setattr(controller_module.power, "idle_seconds", lambda: 0.0)
        control = self._control(qt_app)
        changes = []
        control.paused_changed.connect(changes.append)

        for _ in range(4):
            control._evaluate_activity()

        assert changes == [True]

    def test_clearing_stops_activity_resumes_the_camera(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "session_locked", lambda: True)
        monkeypatch.setattr(controller_module.power, "idle_seconds", lambda: 0.0)
        control = self._control(qt_app)
        control._evaluate_activity()
        assert control.camera.paused

        controller_module.power.session_locked = lambda: False
        control._evaluate_activity()

        assert not control.camera.paused
        assert not control._paused_for_activity
        assert control._timer.isActive()

    def test_pausing_clears_any_screen_dimming(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "session_locked", lambda: True)
        monkeypatch.setattr(controller_module.power, "idle_seconds", lambda: 0.0)
        control = self._control(qt_app)
        dims = []
        control.dim_changed.connect(dims.append)

        control._evaluate_activity()

        assert dims and dims[-1] == 0.0

    def test_pausing_emits_a_paused_state_for_the_ui(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "session_locked", lambda: True)
        monkeypatch.setattr(controller_module.power, "idle_seconds", lambda: 0.0)
        control = self._control(qt_app)
        states = []
        control.updated.connect(states.append)

        control._evaluate_activity()

        assert states and states[-1].paused is True
        assert states[-1].camera_healthy is True, "paused is not the same as broken"

    def test_paused_time_is_not_logged_as_time_at_the_desk(self, qt_app, monkeypatch):
        from postureguard.ui import controller as controller_module

        monkeypatch.setattr(controller_module.power, "session_locked", lambda: True)
        monkeypatch.setattr(controller_module.power, "idle_seconds", lambda: 0.0)
        control = self._control(qt_app)

        control._evaluate_activity()
        for _ in range(5):
            control._tick()  # a stray tick must not sneak a log entry in while paused

        assert control.store.today().tracked_seconds == 0


class TestRecoveryFromAFailedStart:
    """Regression: a camera_index saved from a previous session (removed device,
    shifted driver index, a stale value from before the picker's index-vs-position
    bug was fixed) used to brick the controller permanently. Not just at startup —
    picking a working camera afterwards silently did nothing, because the restart-on-
    camera-change path only ran if the controller had already been running once."""

    def _rig(self, monkeypatch, *, fails_for):
        from postureguard.ui import controller as controller_module
        from postureguard.capture import CameraError

        failing = {fails_for} if isinstance(fails_for, int) else set(fails_for)
        attempts = []

        class FlakyCamera:
            def __init__(self, config):
                self.config = config
                self.aspect = 4 / 3

            def start(self):
                attempts.append(self.config.index)
                if self.config.index in failing:
                    raise CameraError(f"could not open camera {self.config.index}")
                return self

            def read(self):
                return None

            def stop(self):
                pass

        class FakePoseTracker:
            def close(self):
                pass

        monkeypatch.setattr(controller_module, "Camera", FlakyCamera)
        monkeypatch.setattr(controller_module, "PoseTracker", lambda: FakePoseTracker())
        return attempts

    def test_a_camera_that_wont_open_is_reported_not_raised(self, qt_app, monkeypatch):
        self._rig(monkeypatch, fails_for=99)
        control = MonitorController(Config(camera_index=99), SessionStore())
        failures = []
        control.failed.connect(failures.append)

        assert control.start() is False
        assert not control.running
        assert failures and "99" in failures[0]

    def test_switching_to_a_working_camera_after_a_failed_start_actually_retries(
        self, qt_app, monkeypatch
    ):
        self._rig(monkeypatch, fails_for=99)
        control = MonitorController(Config(camera_index=99), SessionStore())
        assert control.start() is False
        assert not control.running

        # The fix: previously gated on `self._running`, which is False right here —
        # so this call used to be a complete no-op, leaving the user stuck with a
        # broken camera and no indication anything had (not) happened.
        control.apply_config(Config(camera_index=0))

        assert control.running
        assert control.camera is not None

    def test_switching_between_two_broken_cameras_still_retries_and_reports(
        self, qt_app, monkeypatch
    ):
        """Not just recovery to a working camera: switching from one broken index to
        a *different* broken index is still a real change and must still attempt to
        open it and report the failure, not go quiet just because it failed before."""
        attempts = self._rig(monkeypatch, fails_for={99, 88})
        control = MonitorController(Config(camera_index=99), SessionStore())
        control.start()
        failures = []
        control.failed.connect(failures.append)

        control.apply_config(Config(camera_index=88))

        assert not control.running
        assert 88 in attempts, "must actually attempt to open the new index"
        assert failures and "88" in failures[0]

    def test_reselecting_the_identical_index_is_not_treated_as_a_change(
        self, qt_app, monkeypatch
    ):
        """Distinct from the bug above: this is legitimately a no-op, not a case that
        needs a retry — camera_index is unchanged, so nothing should reopen."""
        attempts = self._rig(monkeypatch, fails_for=99)
        control = MonitorController(Config(camera_index=99), SessionStore())
        control.start()
        attempts.clear()

        control.apply_config(Config(camera_index=99))

        assert attempts == []
