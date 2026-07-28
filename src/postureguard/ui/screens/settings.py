"""Settings: calibration, how sensitive it is, and how hard it pushes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import paths, theme
from ...calibration import Baseline
from ...config import Config
from ...metrics import describe
from ...session import SessionStore
from ..widgets import Card, PageHeader, button, crisp, label, plain

S = theme.SPACE


class Row(QWidget):
    """A labelled setting: name, one line of consequence, and the control.

    Rows carry their own top rule and padding rather than relying on the card's
    spacing. Settings cards stack many rows, and without a separator they run
    together into one grey wall of text.
    """

    #: Painted rather than added as a widget, so it spans the full card width and does
    #: not participate in the row's own layout maths.
    separator = True

    def __init__(self, title: str, explanation: str, control: QWidget) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, S["md"], 0, S["md"])
        layout.setSpacing(S["lg"])

        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(title, "CardTitle"))
        note = label(explanation, "Body")
        note.setWordWrap(True)
        text.addWidget(note)
        layout.addLayout(text, 1)

        # Fixed, not minimum: a minimum lets a long checkbox caption widen the control
        # column until the whole card overflows its scroll area horizontally.
        control.setFixedWidth(210)
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.control = control
        self._first = False

    def paintEvent(self, event) -> None:
        if self._first:
            return
        painter = QPainter(self)
        pen = QPen(theme.RULE)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        edge = crisp(0, self.devicePixelRatioF())
        painter.drawLine(QPointF(0, edge), QPointF(self.width(), edge))
        painter.end()

    def set_first(self) -> None:
        """The topmost row in a card needs no rule above it."""
        self._first = True
        self.update()


class SliderRow(Row):
    """A slider that always shows what its current position means in words."""

    def __init__(
        self,
        title: str,
        explanation: str,
        minimum: int,
        maximum: int,
        value: int,
        formatter,
    ) -> None:
        holder = QWidget()
        holder.setObjectName("Plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        layout.addWidget(self.slider)

        self._readout = label(formatter(value), "Eyebrow")
        self._readout.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._readout)

        super().__init__(title, explanation, holder)
        self._formatter = formatter
        self.slider.valueChanged.connect(
            lambda v: self._readout.setText(self._formatter(v))
        )


def _when(stamp: str) -> str:
    """An ISO UTC timestamp as something a person would say.

    The stored value is UTC with an offset suffix; showing it raw puts "+00:00" in
    front of the user and reports the wrong hour for anyone outside UTC.
    """
    if not stamp:
        return "at an unknown time"
    try:
        moment = datetime.fromisoformat(stamp)
    except ValueError:
        return "at an unknown time"
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    today = datetime.now(moment.tzinfo).date()
    if moment.date() == today:
        return f"today at {moment.strftime('%H:%M')}"
    if (today - moment.date()).days == 1:
        return f"yesterday at {moment.strftime('%H:%M')}"
    return moment.strftime("on %d %b at %H:%M")


def _sensitivity_words(value: int) -> str:
    scale = value / 100
    if scale < 0.7:
        return f"{scale:.2f}× — very forgiving"
    if scale < 0.95:
        return f"{scale:.2f}× — relaxed"
    if scale <= 1.1:
        return f"{scale:.2f}× — balanced"
    if scale <= 1.5:
        return f"{scale:.2f}× — strict"
    return f"{scale:.2f}× — very strict"


class SettingsScreen(QWidget):
    changed = Signal(object)  # Config
    recalibrate_requested = Signal()

    def __init__(
        self, config: Config, cameras: list | None = None, store: SessionStore | None = None
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

        # --- calibration ---
        calibration = Card(
            "Calibration",
            "Your baseline is what every threshold is measured against. "
            "Recapture it whenever the camera or your chair moves.",
        )
        calibration.add(label("Profile", "Eyebrow"))
        self.profile = QComboBox()
        self._reload_profiles(config.calibration_profile)
        new_profile = button("New…", "Ghost")
        new_profile.clicked.connect(self._create_profile)
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.profile, 1)
        profile_row.addWidget(new_profile)
        calibration.add(plain(profile_row))

        self._baseline_note = label("", "Body")
        self._baseline_note.setWordWrap(True)
        calibration.add(self._baseline_note)
        recalibrate = button("Recalibrate now", "Primary")
        recalibrate.clicked.connect(self.recalibrate_requested)
        row = QHBoxLayout()
        row.addWidget(recalibrate)
        row.addStretch(1)
        calibration.add(plain(row))
        layout.addWidget(calibration)

        # --- detection ---
        detection = Card("Detection")
        self.sensitivity = SliderRow(
            "Sensitivity",
            "How far you have to stray from your baseline before it counts.",
            25, 200, int(config.sensitivity * 100), _sensitivity_words,
        )
        detection.add(self.sensitivity)

        self.reaction = SliderRow(
            "Patience",
            "How long bad posture must hold before it is called a fault. "
            "Shorter catches more; longer ignores fidgeting.",
            2, 40, int(config.react_after_seconds * 10),
            lambda v: f"{v / 10:.1f}s",
        )
        detection.add(self.reaction)

        # Real attached devices, by name. Offering indices that may not exist meant a
        # selection could close a working camera to open nothing.
        self.camera = QComboBox()
        for info in cameras or []:
            self.camera.addItem(info.name, info.index)
        if self.camera.count() == 0:
            self.camera.addItem("No camera found", 0)
            self.camera.setEnabled(False)
        stored = self.camera.findData(config.camera_index)
        # True when the saved camera_index matches no attached device — a removed
        # camera, a driver reshuffle, a stale value. The picker falls back to
        # displaying the first real device below, which looks correct on screen while
        # the broken index stays persisted underneath it. Application checks this
        # flag once, right after construction, and re-emits the corrected value so
        # the fix actually takes effect instead of silently doing nothing until the
        # user happens to touch a control that was never wrong to begin with.
        self.camera_was_corrected = stored < 0 and self.camera.isEnabled()
        self.camera.setCurrentIndex(stored if stored >= 0 else 0)
        detection.add(
            Row(
                "Camera",
                "Which device to watch you with."
                if self.camera.isEnabled()
                else "No camera detected. Connect one and reopen this window.",
                self.camera,
            )
        )

        self.mirror = QCheckBox("Enabled")
        self.mirror.setChecked(config.mirror)
        detection.add(
            Row("Mirroring", "Makes the view behave like a mirror, which is easier to correct against.", self.mirror)
        )

        self.standing_detection = QCheckBox("Enabled")
        self.standing_detection.setChecked(config.standing_detection_enabled)
        detection.add(
            Row(
                "Standing detection",
                "Pause checks while you're standing — your sitting baseline "
                "doesn't apply, so guessing would be worse than not checking.",
                self.standing_detection,
            )
        )
        layout.addWidget(detection)

        # --- interventions ---
        alerts = Card(
            "Interventions",
            "The overlay cue is always on. These control what happens when it is ignored.",
        )
        self.mini_window = QCheckBox("Enabled")
        self.mini_window.setChecked(config.mini_window)
        alerts.add(
            Row(
                "Mini window",
                "A small readout showing live posture and the current fix. Drag it "
                "anywhere; double-click to collapse it to a single line.",
                self.mini_window,
            )
        )

        self.mini_always_on_top = QCheckBox("Always on top")
        self.mini_always_on_top.setChecked(config.mini_always_on_top)
        alerts.add(
            Row(
                "Keep it above other windows",
                "Off lets a maximized app or a full-screen game cover it. A "
                "correction you cannot see is not correcting anything, so this "
                "defaults on.",
                self.mini_always_on_top,
            )
        )

        self.alerts_enabled = QCheckBox("Enabled")
        self.alerts_enabled.setChecked(config.alerts_enabled)
        alerts.add(Row("Notifications", "A prompt naming the fault and the fix.", self.alerts_enabled))

        self.suppress_when_fullscreen = QCheckBox("Enabled")
        self.suppress_when_fullscreen.setChecked(config.suppress_when_fullscreen)
        alerts.add(
            Row(
                "Hold back during fullscreen",
                "Skip the notification and screen dimming while presenting, on a "
                "call, or in a game. The overlay cue stays on.",
                self.suppress_when_fullscreen,
            )
        )

        self.alert_sound = QCheckBox("Enabled")
        self.alert_sound.setChecked(config.alert_sound_enabled)
        alerts.add(
            Row(
                "Alert sound",
                "A short chime alongside the notification — the one channel that "
                "reaches you if you're not looking at this screen at all.",
                self.alert_sound,
            )
        )

        self.toast_after = SliderRow(
            "Notify after",
            "How long a fault must be ignored before the notification appears.",
            5, 120, int(config.toast_after_seconds), lambda v: f"{v}s",
        )
        alerts.add(self.toast_after)

        self.dim_enabled = QCheckBox("Enabled")
        self.dim_enabled.setChecked(config.dim_enabled)
        alerts.add(
            Row("Screen dimming", "The last rung. Fades in gradually and never blocks clicks.", self.dim_enabled)
        )

        self.dim_after = SliderRow(
            "Dim after",
            "Time from the fault starting to the screen beginning to dim.",
            20, 300, int(config.dim_after_seconds), lambda v: f"{v}s",
        )
        alerts.add(self.dim_after)

        self.dim_opacity = SliderRow(
            "Maximum dim",
            "How dark it gets at full escalation.",
            10, 80, int(config.dim_max_opacity * 100), lambda v: f"{v}%",
        )
        alerts.add(self.dim_opacity)

        self.hotkeys_enabled = QCheckBox("Enabled")
        self.hotkeys_enabled.setChecked(config.hotkeys_enabled)
        alerts.add(
            Row(
                "Global hotkeys",
                "Ctrl+Alt+P snoozes, Ctrl+Alt+R recalibrates — from anywhere, even "
                "while another app has focus.",
                self.hotkeys_enabled,
            )
        )

        self.snooze_minutes = QSpinBox()
        self.snooze_minutes.setRange(1, 120)
        self.snooze_minutes.setSuffix(" min")
        self.snooze_minutes.setValue(config.snooze_minutes)
        alerts.add(Row("Snooze length", "How long the Snooze button silences alerts for.", self.snooze_minutes))
        layout.addWidget(alerts)

        # --- breaks ---
        breaks = Card("Breaks")
        self.breaks_enabled = QCheckBox("Enabled")
        self.breaks_enabled.setChecked(config.breaks_enabled)
        breaks.add(
            Row("Break reminders", "Counts only time you are actually at the desk.", self.breaks_enabled)
        )
        self.break_interval = QSpinBox()
        self.break_interval.setRange(5, 180)
        self.break_interval.setSuffix(" min")
        self.break_interval.setValue(config.break_interval_minutes)
        breaks.add(Row("Break interval", "Working time between prompts.", self.break_interval))
        self.weekly_summary_enabled = QCheckBox("Enabled")
        self.weekly_summary_enabled.setChecked(config.weekly_summary_enabled)
        breaks.add(
            Row(
                "Weekly summary",
                "A once-a-week note naming the hour posture held up worst.",
                self.weekly_summary_enabled,
            )
        )
        layout.addWidget(breaks)

        # --- power ---
        power_card = Card(
            "Power",
            "The camera is released — not just idled — while nothing needs watching, "
            "which stops it drawing power and turns its capture light off.",
        )
        self.pause_when_locked = QCheckBox("Enabled")
        self.pause_when_locked.setChecked(config.pause_when_locked)
        power_card.add(
            Row(
                "Pause when locked",
                "Release the camera the moment the session locks.",
                self.pause_when_locked,
            )
        )
        self.pause_after_idle = SliderRow(
            "Pause after inactivity",
            "No keyboard or mouse input for this long releases the camera. Zero disables it.",
            0, 30, config.pause_after_idle_minutes,
            lambda v: "Never" if v == 0 else f"{v} min",
        )
        power_card.add(self.pause_after_idle)
        self.battery_saver = QCheckBox("Enabled")
        self.battery_saver.setChecked(config.battery_saver)
        power_card.add(
            Row(
                "Reduce activity on battery",
                "Halves the camera frame rate while unplugged. Detection is unaffected.",
                self.battery_saver,
            )
        )
        layout.addWidget(power_card)

        # --- startup ---
        startup = Card("Startup")
        self.launch_at_login = QCheckBox("Enabled")
        self.launch_at_login.setChecked(config.launch_at_login)
        startup.add(
            Row(
                "Launch at login",
                "Start PostureGuard automatically when you sign in to Windows.",
                self.launch_at_login,
            )
        )
        self.start_minimized = QCheckBox("Enabled")
        self.start_minimized.setChecked(config.start_minimized)
        startup.add(
            Row(
                "Start minimized",
                "Come up in the tray rather than opening the main window.",
                self.start_minimized,
            )
        )
        layout.addWidget(startup)

        # --- appearance ---
        appearance = Card("Appearance")
        self.theme_mode = QComboBox()
        self.theme_mode.addItem("Dark", "dark")
        self.theme_mode.addItem("Light", "light")
        index = self.theme_mode.findData(config.theme_mode)
        self.theme_mode.setCurrentIndex(index if index >= 0 else 0)
        appearance.add(Row("Theme", "The instrument palette, dark or light.", self.theme_mode))
        layout.addWidget(appearance)

        # --- privacy ---
        privacy = Card("Privacy")
        privacy.add(
            label(
                "Video never leaves this device and is never written to disk. Only derived "
                "numbers — the measurements you see on the Live screen — are stored, in a "
                "local database.",
                "Body",
            )
        )
        self.retention_days = QSpinBox()
        self.retention_days.setRange(0, 730)
        self.retention_days.setSuffix(" days")
        # 0 reads as "Forever" rather than "0 days" — a spinbox at its floor should
        # never look like it is about to delete everything.
        self.retention_days.setSpecialValueText("Forever")
        self.retention_days.setValue(config.retention_days)
        privacy.add(
            Row(
                "Keep history for",
                "History older than this is deleted automatically. The Live screen "
                "and today's stats are never affected.",
                self.retention_days,
            )
        )
        privacy.add(label("Data folder", "Eyebrow"))
        # A filesystem path is a single unbreakable token, so a wrapped QLabel reports
        # the whole path as its minimum width and drags the entire scroll area wider
        # than its viewport — clipping every control on the right. A read-only field
        # scrolls internally instead, and lets the user copy the path out.
        location = QLineEdit(str(paths.data_dir()))
        location.setReadOnly(True)
        location.setObjectName("PathField")
        location.setCursorPosition(0)
        privacy.add(location)

        data_actions = QHBoxLayout()
        export_button = button("Export history…", "Secondary")
        export_button.clicked.connect(self._export_history)
        data_actions.addWidget(export_button)
        delete_button = button("Delete all data…", "Secondary")
        delete_button.clicked.connect(self._delete_all_data)
        data_actions.addWidget(delete_button)
        data_actions.addStretch(1)
        privacy.add(plain(data_actions))
        layout.addWidget(privacy)
        layout.addStretch(1)

        self._connect()
        self._loading = False
        self.refresh()

    def _connect(self) -> None:
        for slider_row in (
            self.sensitivity, self.reaction, self.toast_after,
            self.dim_after, self.dim_opacity, self.pause_after_idle,
        ):
            slider_row.slider.valueChanged.connect(self._emit)
        for check in (
            self.alerts_enabled, self.dim_enabled, self.mirror,
            self.breaks_enabled, self.mini_window, self.mini_always_on_top,
            self.pause_when_locked, self.battery_saver, self.standing_detection,
            self.launch_at_login, self.start_minimized, self.alert_sound,
            self.suppress_when_fullscreen, self.weekly_summary_enabled,
            self.hotkeys_enabled,
        ):
            check.toggled.connect(self._emit)
        for spin in (self.break_interval, self.snooze_minutes, self.retention_days):
            spin.valueChanged.connect(self._emit)
        self.camera.currentIndexChanged.connect(self._emit)
        self.profile.currentTextChanged.connect(self._on_profile_changed)
        self.theme_mode.currentIndexChanged.connect(self._emit)

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
            alerts_enabled=self.alerts_enabled.isChecked(),
            alert_sound_enabled=self.alert_sound.isChecked(),
            suppress_when_fullscreen=self.suppress_when_fullscreen.isChecked(),
            toast_after_seconds=float(self.toast_after.slider.value()),
            dim_enabled=self.dim_enabled.isChecked(),
            dim_after_seconds=float(self.dim_after.slider.value()),
            dim_max_opacity=self.dim_opacity.slider.value() / 100,
            snooze_minutes=self.snooze_minutes.value(),
            hotkeys_enabled=self.hotkeys_enabled.isChecked(),
            breaks_enabled=self.breaks_enabled.isChecked(),
            break_interval_minutes=self.break_interval.value(),
            weekly_summary_enabled=self.weekly_summary_enabled.isChecked(),
            retention_days=self.retention_days.value(),
            mini_window=self.mini_window.isChecked(),
            mini_always_on_top=self.mini_always_on_top.isChecked(),
            pause_when_locked=self.pause_when_locked.isChecked(),
            pause_after_idle_minutes=self.pause_after_idle.slider.value(),
            battery_saver=self.battery_saver.isChecked(),
            start_minimized=self.start_minimized.isChecked(),
            launch_at_login=self.launch_at_login.isChecked(),
            # Carried through, not rebuilt. This constructor rebuilds Config from the
            # visible controls, so any field without one here silently reverts to its
            # default — which would throw away the mini window's saved position.
            mini_collapsed=self.config.mini_collapsed,
            mini_x=self.config.mini_x,
            mini_y=self.config.mini_y,
            mini_screen=self.config.mini_screen,
            calibration_profile=self.profile.currentText() or self.config.calibration_profile,
            theme_mode=self.theme_mode.currentData() or "dark",
        )
        self.changed.emit(self.config)

    def _reload_profiles(self, selected: str) -> None:
        self.profile.blockSignals(True)
        self.profile.clear()
        for name in paths.list_profiles():
            self.profile.addItem(name)
        index = self.profile.findText(selected)
        self.profile.setCurrentIndex(index if index >= 0 else 0)
        self.profile.blockSignals(False)

    def _create_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New profile", "Name this calibration (e.g. \"Standing desk\"):"
        )
        if not ok or not name.strip():
            return
        # paths.list_profiles() only lists profiles with a saved baseline, and this
        # one does not have one yet — added to the combo directly rather than via a
        # reload, which would not find it and silently fall back to "default".
        # Selecting it below leaves the engine with no baseline to load, which is
        # exactly what should start a fresh calibration for it.
        sanitized = paths.sanitize_profile_name(name)
        if self.profile.findText(sanitized) < 0:
            self.profile.addItem(sanitized)
        self.profile.setCurrentText(sanitized)

    def _on_profile_changed(self) -> None:
        if self._loading:
            return
        self._emit()
        self.refresh()

    def _export_history(self) -> None:
        if self.store is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export history", "postureguard-history.csv", "CSV files (*.csv)"
        )
        if not path:
            return
        rows = self.store.export_csv(Path(path))
        QMessageBox.information(
            self, "Export complete", f"Wrote {rows} row{'s' if rows != 1 else ''} to {path}."
        )

    def _delete_all_data(self) -> None:
        if self.store is None:
            return
        confirmed = QMessageBox.question(
            self,
            "Delete all data",
            "This permanently deletes your entire posture history from this device. "
            "Your baseline and settings are not affected. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if confirmed != QMessageBox.StandardButton.Yes:
            return
        self.store.delete_all()
        QMessageBox.information(self, "Data deleted", "Your posture history has been erased.")

    def set_sensitivity(self, value: float) -> None:
        """Reflect a sensitivity change made outside this screen — the automatic
        backoff after repeated snoozes — without re-emitting `changed` for it."""
        self._loading = True
        self.sensitivity.slider.setValue(int(round(value * 100)))
        self._loading = False

    def refresh(self) -> None:
        active_profile = self.profile.currentText() or self.config.calibration_profile
        baseline = Baseline.load(paths.baseline_path(active_profile))
        if baseline is None:
            self._baseline_note.setText(
                "No baseline yet. The Live screen will capture one the first time it sees you."
            )
            return
        self._baseline_note.setText(
            f"Captured {_when(baseline.captured_at)} from {baseline.sample_count} frames. "
            f"Tracking your {describe(baseline.values)}."
        )
