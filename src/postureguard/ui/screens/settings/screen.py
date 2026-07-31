"""Settings: calibration, how sensitive it is, and how hard it pushes.

Assembled from one panel per card (calibration, detection, interventions, breaks,
power, startup, appearance, privacy) so that no single file carries the whole screen.
Each panel owns its own controls and relays a bare ``changed`` signal; this screen is
the only place that knows how to turn "something changed" into a new :class:`Config`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from .... import theme
from ....config import Config
from ....monitor_profile import MonitorProfiles
from ....session import SessionStore
from ...widgets import PageHeader
from .breaks import BreaksPanel
from .calibration import CalibrationPanel
from .detection import DetectionPanel
from .general import AppearancePanel, StartupPanel
from .interventions import InterventionsPanel
from .power import PowerPanel
from .privacy import PrivacyPanel

S = theme.SPACE


class SettingsScreen(QWidget):
    changed = Signal(object)  # Config
    recalibrate_requested = Signal()

    def __init__(
        self,
        config: Config,
        cameras: list | None = None,
        store: SessionStore | None = None,
        monitor_profiles: MonitorProfiles | None = None,
    ) -> None:
        super().__init__()
        self.config = config
        self.store = store
        self._loading = True

        outer = QVBoxLayout(self)
        outer.setContentsMargins(S["xl"], S["xl"], S["xl"], S["xl"])
        outer.setSpacing(S["lg"])

        header = PageHeader("Settings", "Tune how closely it watches and how hard it pushes.")
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # Content must reflow to the available width; a horizontal scrollbar
        # here means a control has escaped the layout, not that the user should scroll.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        layout = QVBoxLayout(host)
        layout.setContentsMargins(0, 0, S["sm"], 0)
        layout.setSpacing(S["lg"])
        scroll.setWidget(host)
        outer.addWidget(scroll, 1)

        self.calibration = CalibrationPanel(
            config.calibration_profile, config.auto_profile_by_monitor, monitor_profiles
        )
        self.calibration.recalibrate_requested.connect(self.recalibrate_requested)
        self.calibration.changed.connect(self._emit)
        layout.addWidget(self.calibration)

        self.detection = DetectionPanel(config, cameras)
        self.detection.changed.connect(self._emit)
        layout.addWidget(self.detection)

        self.interventions = InterventionsPanel(config)
        self.interventions.changed.connect(self._emit)
        layout.addWidget(self.interventions)

        self.breaks = BreaksPanel(config)
        self.breaks.changed.connect(self._emit)
        layout.addWidget(self.breaks)

        self.power = PowerPanel(config)
        self.power.changed.connect(self._emit)
        layout.addWidget(self.power)

        self.startup = StartupPanel(config)
        self.startup.changed.connect(self._emit)
        layout.addWidget(self.startup)

        self.appearance = AppearancePanel(config)
        self.appearance.changed.connect(self._emit)
        layout.addWidget(self.appearance)

        self.privacy = PrivacyPanel(config, store)
        self.privacy.changed.connect(self._emit)
        layout.addWidget(self.privacy)

        layout.addStretch(1)

        # Flattened aliases: external callers (Application) and tests reach into a
        # handful of controls directly, and moving them into sub-panels should not
        # move the public surface too.
        self.profile = self.calibration.profile
        self.sensitivity = self.detection.sensitivity
        self.reaction = self.detection.reaction
        self.camera = self.detection.camera
        self.camera_was_corrected = self.detection.camera_was_corrected
        self.mirror = self.detection.mirror
        self.standing_detection = self.detection.standing_detection
        self.pause_when_locked = self.power.pause_when_locked
        self.pause_after_idle = self.power.pause_after_idle
        self.battery_saver = self.power.battery_saver
        self.theme_mode = self.appearance.theme_mode

        self._loading = False
        self.refresh()

    def _emit(self) -> None:
        # Populating the controls fires their signals; without this guard the screen
        # would emit a config change for every widget it builds at startup.
        if self._loading:
            return
        self.config = Config(
            # currentData(), never currentIndex(): the list position is not the device
            # index once unavailable devices are excluded.
            camera_index=self.camera.currentData() if self.camera.currentData() is not None else 0,
            mirror=self.mirror.isChecked(),
            standing_detection_enabled=self.standing_detection.isChecked(),
            sensitivity=self.sensitivity.slider.value() / 100,
            react_after_seconds=self.reaction.slider.value() / 10,
            alerts_enabled=self.interventions.alerts_enabled.isChecked(),
            alert_sound_enabled=self.interventions.alert_sound.isChecked(),
            suppress_when_fullscreen=self.interventions.suppress_when_fullscreen.isChecked(),
            toast_after_seconds=float(self.interventions.toast_after.slider.value()),
            dim_enabled=self.interventions.dim_enabled.isChecked(),
            dim_after_seconds=float(self.interventions.dim_after.slider.value()),
            dim_max_opacity=self.interventions.dim_opacity.slider.value() / 100,
            snooze_minutes=self.interventions.snooze_minutes.value(),
            hotkeys_enabled=self.interventions.hotkeys_enabled.isChecked(),
            breaks_enabled=self.breaks.breaks_enabled.isChecked(),
            break_interval_minutes=self.breaks.break_interval.value(),
            weekly_summary_enabled=self.breaks.weekly_summary_enabled.isChecked(),
            retention_days=self.privacy.retention_days.value(),
            mini_window=self.interventions.mini_window.isChecked(),
            mini_always_on_top=self.interventions.mini_always_on_top.isChecked(),
            pause_when_locked=self.pause_when_locked.isChecked(),
            pause_after_idle_minutes=self.pause_after_idle.slider.value(),
            battery_saver=self.battery_saver.isChecked(),
            start_minimized=self.startup.start_minimized.isChecked(),
            launch_at_login=self.startup.launch_at_login.isChecked(),
            # Carried through, not rebuilt. This constructor rebuilds Config from the
            # visible controls, so any field without one here silently reverts to its
            # default — which would throw away the mini window's saved position.
            mini_collapsed=self.config.mini_collapsed,
            mini_x=self.config.mini_x,
            mini_y=self.config.mini_y,
            mini_screen=self.config.mini_screen,
            calibration_profile=self.profile.currentText() or self.config.calibration_profile,
            auto_profile_by_monitor=self.calibration.auto_by_monitor.isChecked(),
            theme_mode=self.appearance.theme_mode.currentData() or "dark",
        )
        self.changed.emit(self.config)

    def set_sensitivity(self, value: float) -> None:
        """Reflect a sensitivity change made outside this screen — the automatic
        backoff after repeated snoozes — without re-emitting `changed` for it."""
        self._loading = True
        self.sensitivity.slider.setValue(round(value * 100))
        self._loading = False

    def refresh(self) -> None:
        self.calibration.refresh()
