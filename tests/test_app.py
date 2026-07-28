"""End-to-end coverage for Application — the wiring class in app.py.

Nothing here previously exercised this file directly; every failure it produces only
shows up by actually constructing the real Application and driving it, which is what
caught the bugs these tests pin: a broken saved camera_index used to brick startup
entirely (one error dialog, then exit(1), forever, since the broken value was already
persisted), and even after that was fixed, correcting the camera in Settings after a
failed start silently did nothing because the retry was gated on the controller having
already been running once.

Camera and pose model are monkeypatched (same technique as test_controller.py); a
tmp_path POSTUREGUARD_HOME keeps everything on disk isolated from real user data.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from postureguard import paths  # noqa: E402
from postureguard.app import Application  # noqa: E402
from postureguard.capture import CameraError, CameraInfo  # noqa: E402
from postureguard.config import Config  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Every path.*() helper honours POSTUREGUARD_HOME; route it to a scratch dir so
    tests can never read or write the real user's app data."""
    monkeypatch.setenv("POSTUREGUARD_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def no_dialogs(monkeypatch):
    """QMessageBox.critical blocks on its own nested event loop waiting for a click;
    a test process has nobody to click it. Capture what would have been shown instead
    of letting it hang."""
    shown = []
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *a, **kw: (shown.append(a), None)[1])
    )
    return shown


def rig(monkeypatch, *, fails_for=frozenset(), cameras=(CameraInfo(0, "Test Camera"),)):
    """Stand in for the real Camera/PoseTracker/available_cameras, same approach as
    test_controller.py's FlakyCamera, driven this time through the real Application."""
    from postureguard import app as app_module
    from postureguard.ui import controller as controller_module

    failing = set(fails_for) if not isinstance(fails_for, int) else {fails_for}
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
    monkeypatch.setattr(app_module, "available_cameras", lambda: list(cameras))
    return attempts


class TestNormalStartup:
    def test_a_working_camera_starts_cleanly_with_no_dialog(
        self, qt_app, isolated_home, no_dialogs, monkeypatch
    ):
        rig(monkeypatch, fails_for=frozenset())
        application = Application(Config(camera_index=0, mini_window=False))
        try:
            application.start()
            assert application.controller.running
            assert application.window.isVisible()
            assert no_dialogs == []
        finally:
            application.shutdown()


class TestBrokenCameraDoesNotBrickStartup:
    """The core regression: previously this whole scenario ended in an error dialog
    and the process exiting before the window ever appeared."""

    def test_the_window_still_appears(self, qt_app, isolated_home, no_dialogs, monkeypatch):
        # camera_index matches the one listed device exactly — this is a device that
        # physically fails to open, not a stale index, so the self-heal path (tested
        # separately below) must not interfere with what this test is isolating.
        rig(monkeypatch, fails_for=0, cameras=[CameraInfo(0, "Test Camera")])
        application = Application(Config(camera_index=0, mini_window=False))
        try:
            application.start()
            assert application.window.isVisible()
            assert not application.controller.running
            assert no_dialogs, "the failure must still be reported, just not fatally"
        finally:
            application.shutdown()

    def test_the_broken_index_self_corrects_before_start_is_even_called(
        self, qt_app, isolated_home, no_dialogs, monkeypatch
    ):
        """Application detects the saved camera does not exist, corrects it, and
        retries during __init__ — before main() ever calls start(). By the time the
        caller gets here the controller may already be running."""
        rig(monkeypatch, fails_for=frozenset(), cameras=[CameraInfo(0, "Real Camera")])
        application = Application(Config(camera_index=99, mini_window=False))
        try:
            assert application.config.camera_index == 0
            assert application.controller.running
            assert no_dialogs == [], "a silent, successful self-correction needs no dialog"
        finally:
            application.shutdown()

    def test_the_corrected_index_is_persisted_so_the_fix_is_permanent(
        self, qt_app, isolated_home, no_dialogs, monkeypatch
    ):
        rig(monkeypatch, fails_for=frozenset(), cameras=[CameraInfo(0, "Real Camera")])
        application = Application(Config(camera_index=99, mini_window=False))
        try:
            saved = json.loads(paths.config_path().read_text(encoding="utf-8"))
            assert saved["camera_index"] == 0
        finally:
            application.shutdown()

    def test_a_genuinely_missing_camera_reports_but_still_shows_the_window(
        self, qt_app, isolated_home, no_dialogs, monkeypatch
    ):
        """No devices at all: nothing to self-correct to, so this must degrade to
        the plain failure path rather than crash trying to "fix" a list with
        nothing in it."""
        rig(monkeypatch, fails_for=99, cameras=[])
        application = Application(Config(camera_index=99, mini_window=False))
        try:
            application.start()
            assert application.window.isVisible()
            assert not application.controller.running
        finally:
            application.shutdown()


class TestThemeSwitching:
    def test_changing_theme_in_settings_applies_it_live(
        self, qt_app, isolated_home, no_dialogs, monkeypatch
    ):
        from postureguard import theme

        rig(monkeypatch, fails_for=frozenset())
        application = Application(Config(camera_index=0, mini_window=False))
        try:
            assert theme.mode() == "dark"
            index = application.settings.theme_mode.findData("light")
            application.settings.theme_mode.setCurrentIndex(index)
            assert theme.mode() == "light"
            assert application.config.theme_mode == "light"
        finally:
            application.shutdown()
            theme.set_mode("dark")  # process-global state; never leak into other tests


class TestMiniWindowRemembersItsMonitor:
    def test_falls_back_to_the_primary_screen_when_the_saved_name_is_unknown(
        self, qt_app, isolated_home, no_dialogs, monkeypatch
    ):
        rig(monkeypatch, fails_for=frozenset())
        application = Application(Config(camera_index=0, mini_window=False, mini_screen="a monitor that unplugged itself"))
        try:
            assert application._resolve_mini_screen() is QApplication.primaryScreen()
        finally:
            application.shutdown()

    def test_moving_the_mini_window_persists_the_screen_it_landed_on(
        self, qt_app, isolated_home, no_dialogs, monkeypatch
    ):
        rig(monkeypatch, fails_for=frozenset())
        application = Application(Config(camera_index=0, mini_window=True))
        try:
            application._place_mini()
            application._remember_mini_position(application.mini.x(), application.mini.y())
            primary = QApplication.primaryScreen()
            assert application.config.mini_screen == (primary.name() if primary else "")
        finally:
            application.shutdown()


class TestFixingTheCameraFromSettingsAfterAFailedStart:
    """Distinct from the self-heal above: this is the user manually picking a
    different camera in the Settings screen after the app already came up broken."""

    def test_picking_a_working_camera_in_settings_actually_retries(
        self, qt_app, isolated_home, no_dialogs, monkeypatch
    ):
        # Two devices, only index 0 works — mirrors a real machine with both a
        # broken/removed entry and a real webcam.
        rig(
            monkeypatch, fails_for=7,
            cameras=[CameraInfo(0, "Working Camera"), CameraInfo(7, "Ghost Camera")],
        )
        application = Application(Config(camera_index=7, mini_window=False))
        try:
            application.start()
            assert not application.controller.running

            # This is exactly the user action the second bug broke: with the
            # controller never having successfully run, apply_config's restart used
            # to be gated on `self._running`, which was False, so this used to be a
            # complete no-op.
            index = application.settings.camera.findData(0)
            application.settings.camera.setCurrentIndex(index)

            assert application.controller.running
            assert application.config.camera_index == 0
        finally:
            application.shutdown()
