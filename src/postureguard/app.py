"""Application entry point: assembles the window, the controller, and the tray."""

from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import paths
from .alerts import DimOverlay, Toast, app_icon
from .config import Config
from .session import SessionStore
from .overlay import PostureOverlay, ViewModel
from .ui.controller import MonitorController
from .ui.design import stylesheet
from .ui.screens.exercises import ExercisesScreen
from .ui.screens.history import HistoryScreen
from .ui.screens.live import LiveScreen
from .ui.screens.settings import SettingsScreen
from .ui.window import MainWindow

log = logging.getLogger(__name__)


class Application:
    """Wiring. Deliberately the only place that knows about every part."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._shut_down = False
        self._explained_tray = False
        self.store = SessionStore(paths.database_path())
        self.controller = MonitorController(config, self.store)

        self.window = MainWindow()
        self.toast = Toast()
        self.dim = DimOverlay(config.dim_max_opacity)
        self.mini = PostureOverlay(config.thresholds(), collapsed=config.mini_collapsed)

        self.live = LiveScreen(config.thresholds(), self.store)
        self.history = HistoryScreen(self.store)
        self.exercises = ExercisesScreen(self.store)
        self.settings = SettingsScreen(config)

        self.window.add_screen("live", self.live)
        self.window.add_screen("history", self.history)
        self.window.add_screen("exercises", self.exercises)
        self.window.add_screen("settings", self.settings)
        self.window.show_screen("live")

        self.tray = self._build_tray()
        self._connect()

    # --- wiring -------------------------------------------------------------------

    def _connect(self) -> None:
        self.controller.updated.connect(self.window.on_state)
        self.controller.updated.connect(self.live.on_state)
        self.controller.updated.connect(self._update_mini)

        self.mini.open_requested.connect(self._show_window)
        self.mini.snooze_requested.connect(lambda: self.controller.snooze())
        self.mini.recalibrate_requested.connect(self.controller.recalibrate)
        self.mini.hide_requested.connect(self._hide_mini)
        self.mini.moved.connect(self._remember_mini_position)
        self.mini.collapsed_changed.connect(self._remember_mini_collapsed)
        self.controller.toast_requested.connect(self.toast.present)
        self.controller.dim_changed.connect(self.dim.set_progress)
        self.controller.break_due.connect(self._on_break_due)
        self.controller.failed.connect(self._on_failure)
        self.controller.baseline_captured.connect(self.settings.refresh)

        self.live.snooze_requested.connect(self.controller.snooze)
        self.live.recalibrate_requested.connect(self.controller.recalibrate)
        self.live.mini_toggled.connect(self.toggle_mini)
        self.toast.snoozed.connect(self.controller.snooze)
        self.exercises.break_taken.connect(self.controller.breaks.taken)

        self.settings.changed.connect(self._on_config_changed)
        self.settings.recalibrate_requested.connect(self._on_recalibrate_from_settings)

        # Closing the window hides it; monitoring continues from the tray. Tearing the
        # camera down here would silently stop the thing the user installed the app
        # for, with no indication that it had stopped.
        self.window.closing.connect(self._on_window_closed)

    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(app_icon())
        tray.setToolTip("PostureGuard")

        menu = QMenu()
        show = QAction("Open PostureGuard", menu)
        show.triggered.connect(self._show_window)
        menu.addAction(show)

        self._mini_action = QAction("Show mini window", menu)
        self._mini_action.setCheckable(True)
        self._mini_action.setChecked(self.config.mini_window)
        self._mini_action.triggered.connect(self.set_mini_visible)
        menu.addAction(self._mini_action)

        snooze = QAction("Snooze alerts", menu)
        snooze.triggered.connect(lambda: self.controller.snooze())
        menu.addAction(snooze)

        recalibrate = QAction("Recalibrate", menu)
        recalibrate.triggered.connect(self.controller.recalibrate)
        menu.addAction(recalibrate)

        menu.addSeparator()
        quit_action = QAction("Quit", menu)
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)

        tray.setContextMenu(menu)
        tray.activated.connect(
            lambda reason: self._show_window()
            if reason == QSystemTrayIcon.ActivationReason.Trigger
            else None
        )
        tray.show()
        return tray

    # --- handlers -----------------------------------------------------------------

    def _show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _on_break_due(self, routine) -> None:
        self.toast.present(
            "Time for a break",
            f"{routine.reason} {len(routine.exercises)} exercises, "
            f"about {routine.seconds // 60} minutes.",
        )
        self.exercises.refresh()

    def _on_config_changed(self, config: Config) -> None:
        # The settings screen owns whether the mini window exists; the window itself
        # owns where it sits and whether it is collapsed. Settings has no control for
        # those, and its copy of them goes stale the moment the user drags the window,
        # so they are read back from the live truth rather than from the emitted copy.
        config.mini_collapsed = self.mini.collapsed
        config.mini_x, config.mini_y = self.config.mini_x, self.config.mini_y

        was_shown = self.config.mini_window
        self.config = config
        config.save(paths.config_path())
        self.controller.apply_config(config)
        self.dim.max_opacity = config.dim_max_opacity
        self.live.video.thresholds = config.thresholds()
        self.mini.thresholds = config.thresholds()

        if config.mini_window != was_shown:
            self.set_mini_visible(config.mini_window)

    def _on_recalibrate_from_settings(self) -> None:
        self.controller.recalibrate()
        self.window.show_screen("live")

    # --- mini window ---------------------------------------------------------------

    def _update_mini(self, state) -> None:
        if not self.mini.isVisible():
            return
        self.mini.show_model(
            ViewModel(
                frame=state.frame,
                landmarks=state.reading.landmarks,
                metrics=state.reading.metrics,
                faults=state.reading.faults,
                baseline=state.reading.baseline,
                aspect=state.aspect,
                status=state.reading.status,
                message=state.reading.message,
                urgency=int(state.intervention.level),
                held_seconds=state.intervention.held_seconds,
            )
        )

    def _place_mini(self) -> None:
        """Restore the saved corner, or default to bottom-right on first run."""
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        x, y = self.config.mini_x, self.config.mini_y
        if x < 0 or y < 0:
            x = area.right() - self.mini.width() - 24
            y = area.bottom() - self.mini.height() - 24
        # A saved position can land off-screen when a monitor is unplugged. Clamp it
        # back into view rather than leaving the window unreachable.
        x = max(area.left(), min(x, area.right() - self.mini.width()))
        y = max(area.top(), min(y, area.bottom() - self.mini.height()))
        self.mini.move(x, y)

    def _remember_mini_position(self, x: int, y: int) -> None:
        self.config.mini_x, self.config.mini_y = x, y
        self.config.save(paths.config_path())

    def _remember_mini_collapsed(self, collapsed: bool) -> None:
        self.config.mini_collapsed = collapsed
        self.config.save(paths.config_path())

    def set_mini_visible(self, visible: bool) -> None:
        if visible:
            self._place_mini()
            self.mini.show()
        else:
            self.mini.hide()
        self.config.mini_window = visible
        self.config.save(paths.config_path())
        self._mini_action.setChecked(visible)
        self.live.set_mini_shown(visible)

    def _hide_mini(self) -> None:
        self.set_mini_visible(False)

    def toggle_mini(self) -> None:
        self.set_mini_visible(not self.mini.isVisible())

    def _on_window_closed(self) -> None:
        # Say so once. Silently continuing to watch someone through their webcam after
        # they closed the window is not a surprise worth saving them from.
        if not self._explained_tray and self.tray.isSystemTrayAvailable():
            self._explained_tray = True
            self.tray.showMessage(
                "PostureGuard is still watching",
                "Monitoring continues in the background. Quit from the tray icon to stop.",
                app_icon(),
                4000,
            )

    def _on_failure(self, message: str) -> None:
        QMessageBox.critical(self.window, "PostureGuard", message)

    def start(self) -> bool:
        if not self.controller.start():
            return False
        if self.config.mini_window:
            self._place_mini()
            self.mini.show()
        self.live.set_mini_shown(self.config.mini_window)
        if not self.config.start_minimized:
            self.window.show()
        return True

    def quit(self) -> None:
        """Genuinely exit. Closing the window only hides it — the tray keeps running."""
        self.shutdown()
        self.tray.hide()
        QApplication.quit()

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self.controller.stop()
        self.dim.hide()
        self.toast.hide()
        self.mini.hide()
        self.store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="postureguard",
        description="Real-time posture tracking and correction. Runs entirely locally.",
    )
    parser.add_argument("--camera", type=int, default=None, help="camera index override")
    parser.add_argument(
        "--recalibrate",
        action="store_true",
        help="discard the stored baseline and calibrate again — do this whenever the "
        "camera or chair moves",
    )
    parser.add_argument("--verbose", action="store_true", help="log pipeline detail")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    qt = QApplication(sys.argv[:1])
    qt.setApplicationName("PostureGuard")
    qt.setWindowIcon(app_icon())
    qt.setStyleSheet(stylesheet())
    # The tray keeps the app alive; closing the window should not end the session.
    qt.setQuitOnLastWindowClosed(False)

    config = Config.load(paths.config_path())
    if args.camera is not None:
        config.camera_index = args.camera
    if args.recalibrate:
        paths.baseline_path().unlink(missing_ok=True)

    application = Application(config)
    if not application.start():
        return 1

    qt.aboutToQuit.connect(application.shutdown)
    return qt.exec()


if __name__ == "__main__":
    raise SystemExit(main())
