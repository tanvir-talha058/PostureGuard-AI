"""Application entry point: assembles the window, the controller, and the tray."""

from __future__ import annotations

import argparse
import logging
import sys

from PySide6.QtCore import QAbstractEventDispatcher, Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from . import autostart, paths, sound, theme
from .ai import cue_variants as ai_cue_variants
from .ai import exercise_context as ai_exercise_context
from .ai import insights as ai_insights
from .ai import weekly_summary as ai_weekly_summary
from .ai.cue_variants import pick as pick_cue_variant
from .ai.worker import AskWorker
from .alerts import DimOverlay, Toast, app_icon
from .capture import available_cameras
from .config import Config
from .hotkeys import GlobalHotkeys
from .monitor_profile import MonitorProfiles, fingerprint
from .overlay import PostureOverlay, ViewModel
from .session import SessionStore
from .ui.controller import MonitorController
from .ui.design import stylesheet
from .ui.screens.exercises import ExercisesScreen
from .ui.screens.history import HistoryScreen
from .ui.screens.insights import InsightsScreen
from .ui.screens.live import LiveScreen
from .ui.screens.settings import SettingsScreen
from .ui.window import MainWindow
from .weekly_summary import WeeklySummaryGate, build_message

log = logging.getLogger(__name__)

#: Retention is measured in months, not minutes — checking once a day is more than
#: enough, and an app that is tray-resident for weeks at a time still needs *some*
#: periodic check beyond the one at startup.
RETENTION_CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000


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
        self.mini = PostureOverlay(
            collapsed=config.mini_collapsed, always_on_top=config.mini_always_on_top
        )

        self.live = LiveScreen(config.thresholds(), self.store)
        self.history = HistoryScreen(
            self.store, paths.baseline_path(config.calibration_profile)
        )
        self.exercises = ExercisesScreen(self.store)
        self.insights = InsightsScreen(self.store)
        self._monitor_profiles = MonitorProfiles.load(paths.monitor_profiles_path())
        # Real devices, by name. The picker used to offer a fixed "Camera 0/1/2" whether
        # or not those existed, so selecting one could tear down a working camera to
        # open nothing.
        self.settings = SettingsScreen(
            config, available_cameras(), self.store, self._monitor_profiles
        )

        self.window.add_screen("live", self.live)
        self.window.add_screen("history", self.history)
        self.window.add_screen("exercises", self.exercises)
        self.window.add_screen("insights", self.insights)
        self.window.add_screen("settings", self.settings)
        self.window.show_screen("live")

        self.tray = self._build_tray()
        self.hotkeys = self._build_hotkeys()
        self._connect()

        if self.settings.camera_was_corrected:
            # The saved camera does not exist on this machine. The picker already
            # fell back to showing a real device; this makes that correction actually
            # take effect — saving it and retrying the camera open — rather than
            # leaving Settings displaying a working camera while the broken index
            # underneath it stays saved to disk until something else happens to
            # touch the control. Runs before controller.start() is ever called (that
            # happens later, from main()), so the very first camera open attempt
            # uses the corrected index.
            self.settings._emit()

        # Same reasoning as the camera correction above: runs before controller.start()
        # so the very first camera open already uses the right profile's baseline,
        # rather than starting on "default" and switching a moment later.
        self._maybe_auto_switch_profile()

        # Reconciled once at startup, not just on a settings change: the launch
        # command embeds this executable's own path, which can drift after an
        # update or a move even though the setting itself never changed.
        autostart.apply(self.config.launch_at_login)

        self.weekly_summary = WeeklySummaryGate.load(paths.weekly_summary_path())

        self._retention_timer = QTimer()
        self._retention_timer.setInterval(RETENTION_CHECK_INTERVAL_MS)
        self._retention_timer.timeout.connect(self._purge_old_history)
        self._retention_timer.timeout.connect(self._maybe_show_weekly_summary)
        self._retention_timer.start()
        # QTimer.start() fires only after the first interval elapses; an install that
        # has been running since before this feature existed should not have to wait
        # a full day to actually get pruned.
        self._purge_old_history()
        self._maybe_show_weekly_summary()

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
        self.controller.toast_requested.connect(self._on_toast_requested)
        self.controller.dim_changed.connect(self.dim.set_progress)
        self.controller.break_due.connect(self._on_break_due)
        self.controller.failed.connect(self._on_failure)
        self.controller.baseline_captured.connect(self.settings.refresh)
        self.controller.camera_health_changed.connect(self._on_camera_health)
        self.controller.paused_changed.connect(self._on_paused_changed)
        self.controller.sensitivity_backed_off.connect(self._on_sensitivity_backed_off)

        # The frame rate only needs to be smooth for a window actually being watched;
        # the mini window's correction is legible at a far slower rate.
        self.window.shown.connect(lambda: self.controller.set_window_visible(True))
        self.window.hidden.connect(lambda: self.controller.set_window_visible(False))

        self.live.snooze_requested.connect(self.controller.snooze)
        self.live.recalibrate_requested.connect(self.controller.recalibrate)
        self.live.mini_toggled.connect(self.toggle_mini)
        self.toast.snoozed.connect(self.controller.snooze)
        self.exercises.break_taken.connect(self.controller.breaks.taken)
        self.insights.asked.connect(self._on_insights_asked)

        self.settings.changed.connect(self._on_config_changed)
        self.settings.recalibrate_requested.connect(self._on_recalibrate_from_settings)
        self.settings.regenerate_cue_variants_requested.connect(
            self._on_regenerate_cue_variants
        )

        # A dock/undock changes the connected monitors without restarting the app —
        # the startup check alone would miss that.
        qt = QApplication.instance()
        if qt is not None:
            qt.screenAdded.connect(self._maybe_auto_switch_profile)
            qt.screenRemoved.connect(self._maybe_auto_switch_profile)

        self.window.sidebar.theme_toggle_requested.connect(self._on_theme_toggle_requested)

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

    def _build_hotkeys(self) -> GlobalHotkeys:
        hotkeys = GlobalHotkeys(
            on_snooze=lambda: self.controller.snooze(),
            on_recalibrate=self.controller.recalibrate,
        )
        dispatcher = QAbstractEventDispatcher.instance()
        if dispatcher is not None:
            dispatcher.installNativeEventFilter(hotkeys)
        if self.config.hotkeys_enabled:
            hotkeys.register()
        return hotkeys

    # --- handlers -----------------------------------------------------------------

    def _show_window(self) -> None:
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()

    def _on_toast_requested(self, title: str, cue: str) -> None:
        self.toast.present(title, cue)
        if self.config.alert_sound_enabled:
            sound.play_alert()

    def _on_sensitivity_backed_off(self, sensitivity: float) -> None:
        self.config.sensitivity = sensitivity
        self.config.save(paths.config_path())
        self.controller.apply_config(self.config)
        self.settings.set_sensitivity(sensitivity)
        self.toast.present(
            "Sensitivity eased off",
            "A few snoozes today, so PostureGuard backed off a notch. "
            "Adjust anytime in Settings.",
            theme.IN_TOLERANCE,
        )

    def _on_break_due(self, routine) -> None:
        self.toast.present(
            "Time for a break",
            f"{routine.reason} {len(routine.exercises)} exercises, "
            f"about {routine.seconds // 60} minutes.",
        )
        self.exercises.refresh()
        if self.config.ai_exercise_context_enabled and self.config.ai_api_key:
            dominant = self.store.dominant_fault(days=7)
            api_key = self.config.ai_api_key
            self._exercise_context_worker = AskWorker(
                lambda: ai_exercise_context.generate_intro(dominant, self.store, api_key)
            )
            self._exercise_context_worker.finished_with.connect(self.exercises.set_ai_intro)
            self._exercise_context_worker.start()

    def _on_insights_asked(self, question: str) -> None:
        if not self.config.ai_insights_enabled or not self.config.ai_api_key:
            self.insights.show_no_key()
            return
        payload = self.insights.stats_payload()
        if payload is None:
            self.insights.show_answer(
                "Not enough tracked history yet to answer questions — check back after "
                "a few days of use."
            )
            return
        self.insights.show_asking()
        api_key = self.config.ai_api_key
        self._insights_worker = AskWorker(
            lambda: ai_insights.answer_question(payload, question, api_key)
        )
        self._insights_worker.finished_with.connect(self.insights.show_answer)
        self._insights_worker.start()

    def _on_config_changed(self, config: Config) -> None:
        # The settings screen owns whether the mini window exists; the window itself
        # owns where it sits and whether it is collapsed. Settings has no control for
        # those, and its copy of them goes stale the moment the user drags the window,
        # so they are read back from the live truth rather than from the emitted copy.
        config.mini_collapsed = self.mini.collapsed
        config.mini_x, config.mini_y = self.config.mini_x, self.config.mini_y

        was_shown = self.config.mini_window
        retention_changed = config.retention_days != self.config.retention_days
        login_changed = config.launch_at_login != self.config.launch_at_login
        hotkeys_changed = config.hotkeys_enabled != self.config.hotkeys_enabled
        theme_changed = config.theme_mode != self.config.theme_mode
        self.config = config
        if login_changed:
            autostart.apply(config.launch_at_login)
        if hotkeys_changed:
            self.hotkeys.register() if config.hotkeys_enabled else self.hotkeys.unregister()
        if theme_changed:
            self._apply_theme_mode(config.theme_mode)
        config.save(paths.config_path())
        self.controller.apply_config(config)
        self.dim.max_opacity = config.dim_max_opacity
        self.live.video.thresholds = config.thresholds()
        self.mini.set_always_on_top(config.mini_always_on_top)

        if config.mini_window != was_shown:
            self.set_mini_visible(config.mini_window)
        if retention_changed:
            # Shortening the window should take effect now, not tomorrow.
            self._purge_old_history()

    def _apply_theme_mode(self, mode: str) -> None:
        """Swap the palette and make every already-built surface catch up.

        theme.set_mode() only reassigns the colour tokens themselves; the
        stylesheet is a string baked at setStyleSheet() time, and anything painted
        with QPainter (the mini window, the Live screen's skeleton, the charts)
        only reads the new colours on its *next* repaint, which nothing here
        forces on its own.
        """
        theme.set_mode(mode)
        self.window.sidebar.set_theme_label(mode)
        qt = QApplication.instance()
        if qt is None:
            return
        qt.setStyleSheet(stylesheet())
        for widget in qt.allWidgets():
            widget.update()

    def _on_theme_toggle_requested(self) -> None:
        """Flips the Settings dropdown rather than applying a mode directly, so
        persistence and every other listener go through the one path a manual
        dropdown change already uses instead of a second copy of that logic."""
        target = "light" if theme.mode() == "dark" else "dark"
        self.settings.theme_mode.setCurrentIndex(self.settings.theme_mode.findData(target))

    def _on_recalibrate_from_settings(self) -> None:
        self.controller.recalibrate()
        self.window.show_screen("live")

    def _on_regenerate_cue_variants(self) -> None:
        if not self.config.ai_api_key:
            self.toast.present("AI features", "Add an API key first.", theme.WARNING)
            return
        api_key = self.config.ai_api_key
        self.settings.ai.regenerate.setEnabled(False)
        self._cue_variant_worker = AskWorker(lambda: ai_cue_variants.generate_variants(api_key))
        self._cue_variant_worker.finished_with.connect(self._on_cue_variants_ready)
        self._cue_variant_worker.start()

    def _on_cue_variants_ready(self, cache) -> None:
        self.settings.ai.regenerate.setEnabled(True)
        if cache is None:
            self.toast.present(
                "AI features", "Couldn't generate phrasings — check the API key.", theme.WARNING
            )
            return
        cache.save(paths.cue_variants_path())
        self.controller.reload_cue_variants()
        self.toast.present("AI features", "Correction phrasing refreshed.", theme.IN_TOLERANCE)

    def _maybe_auto_switch_profile(self, *_args) -> None:
        """Switch calibration_profile if the connected monitors match a remembered setup.

        Goes through the profile combo rather than building a Config directly, so
        this reuses the exact pathway a manual switch in Settings already goes
        through (CalibrationPanel picks up the change, persistence and the
        controller reload happen via the usual `changed` -> `_on_config_changed`
        route) instead of a second, easily-diverging copy of that logic.
        """
        if not self.config.auto_profile_by_monitor:
            return
        screens = [
            (screen.name(), screen.size().width(), screen.size().height())
            for screen in QApplication.screens()
        ]
        target = self._monitor_profiles.get(fingerprint(screens))
        if target is None or target == self.settings.profile.currentText():
            return
        index = self.settings.profile.findText(target)
        if index < 0:
            # Remembered for a profile that no longer has a saved baseline.
            return
        self.settings.profile.setCurrentIndex(index)

    def _maybe_show_weekly_summary(self) -> None:
        if not self.config.weekly_summary_enabled:
            return
        if not self.weekly_summary.last_shown:
            # Nothing to summarize on day one. Seed the anchor so a summary becomes
            # due one interval from now rather than firing on the very first launch.
            self.weekly_summary.mark_shown()
            self.weekly_summary.save_state(paths.weekly_summary_path())
            return
        if not self.weekly_summary.due():
            return
        self.weekly_summary.mark_shown()
        self.weekly_summary.save_state(paths.weekly_summary_path())

        if self.config.ai_weekly_summary_enabled and self.config.ai_api_key:
            payload = ai_weekly_summary.build_stats_payload(self.store)
            if payload is not None:
                api_key = self.config.ai_api_key
                self._weekly_summary_worker = AskWorker(
                    lambda: ai_weekly_summary.generate_message(payload, api_key)
                )
                self._weekly_summary_worker.finished_with.connect(
                    self._on_weekly_summary_ready
                )
                self._weekly_summary_worker.start()
                return

        self._show_weekly_summary(build_message(self.store))

    def _on_weekly_summary_ready(self, message: str | None) -> None:
        # A None from the AI path (no network, refusal, timeout) falls back to the
        # same static one-liner every other launch already uses.
        self._show_weekly_summary(message if message is not None else build_message(self.store))

    def _show_weekly_summary(self, message: str | None) -> None:
        if message is not None:
            self.toast.present("Your week in posture", message, theme.IN_TOLERANCE)

    def _purge_old_history(self) -> None:
        removed = self.store.purge_older_than(self.config.retention_days)
        if removed:
            log.info(
                "Purged %d history row(s) older than %d days",
                removed, self.config.retention_days,
            )
            # The History screen aggregates from the database directly; if it is the
            # visible screen right now, a purge behind its back should not leave it
            # showing rows that no longer exist.
            self.history.refresh()

    # --- mini window ---------------------------------------------------------------

    def _update_mini(self, state) -> None:
        if not self.mini.isVisible():
            return
        fault = state.reading.faults[0] if state.reading.faults else None
        cue_text = ""
        action_text = ""
        if fault is not None and self.config.ai_cue_variants_enabled:
            cue_text = pick_cue_variant(self.controller.cue_variants, fault.kind, fault.cue)
            action_text = pick_cue_variant(
                self.controller.cue_variants, fault.kind, fault.action, field="action"
            )
        self.mini.show_model(
            ViewModel(
                metrics=state.reading.metrics,
                faults=state.reading.faults,
                status=state.reading.status,
                message=state.reading.message,
                urgency=int(state.intervention.level),
                held_seconds=state.intervention.held_seconds,
                cue_text=cue_text,
                action_text=action_text,
            )
        )

    def _resolve_mini_screen(self):
        """The screen the mini window last lived on, or the primary if unplugged.

        A saved position is only meaningful relative to the monitor it was placed
        on — reapplying it against whatever screen happens to be primary today can
        strand the panel on the wrong display when a second monitor is disconnected
        or the arrangement changes.
        """
        name = self.config.mini_screen
        if name:
            for screen in QApplication.screens():
                if screen.name() == name:
                    return screen
        return QApplication.primaryScreen()

    def _place_mini(self) -> None:
        """Restore the saved corner, or default to bottom-right on first run."""
        screen = self._resolve_mini_screen()
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
        screen = self.mini.screen()
        if screen is not None:
            self.config.mini_screen = screen.name()
        self.config.save(paths.config_path())

    def _remember_mini_collapsed(self, collapsed: bool) -> None:
        # No save here: overlay.set_collapsed() always emits `moved` right after
        # `collapsed_changed` (it repositions to keep the bottom edge anchored), so
        # _remember_mini_position's save a moment later covers this field too —
        # saving here as well would just write the same file twice per toggle.
        self.config.mini_collapsed = collapsed

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

    def _on_paused_changed(self, paused: bool) -> None:
        """Reflect an idle/lock pause in the tray tooltip only.

        No toast: pausing on lock or idle is routine, expected behaviour that will
        happen many times a day. A toast every time would be exactly the kind of
        thing that gets a tool like this disabled by Wednesday. The sidebar, mini
        window and Live screen already say "Paused" for anyone who looks.
        """
        self.tray.setToolTip("PostureGuard — paused" if paused else "PostureGuard")

    def _on_camera_health(self, healthy: bool) -> None:
        """Tell the user when monitoring actually stops, and when it resumes.

        The window and mini window both show the state, but neither may be visible —
        the app is designed to run from the tray. Silently watching nothing is the one
        failure this tool cannot afford to keep to itself.
        """
        if healthy:
            self.tray.setToolTip("PostureGuard")
            self.toast.present(
                "Camera reconnected", "Monitoring has resumed.", theme.IN_TOLERANCE
            )
            # A camera that failed on the very first start() never got the mini
            # window placed or shown at all (start() gates both on that first
            # attempt succeeding) — reconnecting is the only signal that a launch
            # like that gets, so it is also the only chance to catch it up.
            if self.config.mini_window and not self.mini.isVisible():
                self._place_mini()
                self.mini.show()
            return
        self.tray.setToolTip("PostureGuard — camera disconnected")
        self.toast.present(
            "Camera disconnected",
            "Nothing is being monitored. Reconnect the camera, or choose another "
            "in Settings.",
            theme.WARNING,
        )

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

    def start(self) -> None:
        # A camera that fails to open — wrong saved index, unplugged, in use
        # elsewhere — must not prevent the window from appearing. It used to: the
        # whole app would show one error dialog and exit(1), and because the broken
        # camera_index was already persisted, every subsequent launch repeated the
        # exact same failure with no way to reach Settings and fix it. The error is
        # still reported (controller.start() emits `failed`, shown as a dialog by
        # _on_failure), but the window comes up regardless so the only way out of a
        # bad camera selection is never "delete config.json by hand".
        running = self.controller.start()
        if self.config.mini_window and running:
            self._place_mini()
            self.mini.show()
        self.live.set_mini_shown(self.config.mini_window and running)
        # Force the window into view on failure even if start_minimized is set —
        # minimized *and* broken would be invisible and unrecoverable from the tray.
        if not self.config.start_minimized or not running:
            self.window.show()

    def quit(self) -> None:
        """Genuinely exit. Closing the window only hides it — the tray keeps running."""
        self.shutdown()
        self.tray.hide()
        QApplication.quit()

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self._retention_timer.stop()
        self.hotkeys.unregister()
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

    # Must be set before QApplication exists. PassThrough keeps the exact fractional
    # scale factor (1.5 on this project's own dev display) rather than Qt's default
    # of rounding it to the nearest whole number first — the default is what most
    # visibly breaks pixel-grid alignment (see ui/widgets.crisp) on a 125%/150% screen.
    config = Config.load(paths.config_path())
    if args.camera is not None:
        config.camera_index = args.camera
    if args.recalibrate:
        paths.baseline_path(config.calibration_profile).unlink(missing_ok=True)
    # Set before the stylesheet is ever generated, or the very first paint would be
    # dark regardless of what was saved and only catch up on the next config change.
    theme.set_mode(config.theme_mode)

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    qt = QApplication(sys.argv[:1])
    qt.setApplicationName("PostureGuard")
    qt.setWindowIcon(app_icon())
    qt.setStyleSheet(stylesheet())
    # The tray keeps the app alive; closing the window should not end the session.
    qt.setQuitOnLastWindowClosed(False)

    application = Application(config)
    # start() always brings the window up, even if the camera failed to open — see
    # its docstring-equivalent comment. There is no longer a startup condition where
    # exiting before qt.exec() is the right call.
    application.start()

    qt.aboutToQuit.connect(application.shutdown)
    return qt.exec()


if __name__ == "__main__":
    raise SystemExit(main())
