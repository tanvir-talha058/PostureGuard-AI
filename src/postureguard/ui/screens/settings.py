"""Settings: calibration, how sensitive it is, and how hard it pushes."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ... import paths, theme
from ...calibration import Baseline
from ...config import Config
from ..widgets import Card, PageHeader, button, label, plain

S = theme.SPACE


class Row(QWidget):
    """A labelled setting: name, one line of consequence, and the control."""

    def __init__(self, title: str, explanation: str, control: QWidget) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
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

    def __init__(self, config: Config, camera_names: list[str] | None = None) -> None:
        super().__init__()
        self.config = config
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

        self.camera = QComboBox()
        for index, name in enumerate(camera_names or ["Camera 0", "Camera 1", "Camera 2"]):
            self.camera.addItem(name, index)
        self.camera.setCurrentIndex(min(config.camera_index, self.camera.count() - 1))
        detection.add(Row("Camera", "Which device to watch you with.", self.camera))

        self.mirror = QCheckBox("Enabled")
        self.mirror.setChecked(config.mirror)
        detection.add(
            Row("Mirroring", "Makes the view behave like a mirror, which is easier to correct against.", self.mirror)
        )
        layout.addWidget(detection)

        # --- interventions ---
        alerts = Card(
            "Interventions",
            "The overlay cue is always on. These control what happens when it is ignored.",
        )
        self.alerts_enabled = QCheckBox("Enabled")
        self.alerts_enabled.setChecked(config.alerts_enabled)
        alerts.add(Row("Notifications", "A prompt naming the fault and the fix.", self.alerts_enabled))

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
        layout.addWidget(breaks)

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
        layout.addWidget(privacy)
        layout.addStretch(1)

        self._connect()
        self._loading = False
        self.refresh()

    def _connect(self) -> None:
        for slider_row in (
            self.sensitivity, self.reaction, self.toast_after,
            self.dim_after, self.dim_opacity,
        ):
            slider_row.slider.valueChanged.connect(self._emit)
        for check in (self.alerts_enabled, self.dim_enabled, self.mirror, self.breaks_enabled):
            check.toggled.connect(self._emit)
        for spin in (self.break_interval, self.snooze_minutes):
            spin.valueChanged.connect(self._emit)
        self.camera.currentIndexChanged.connect(self._emit)

    def _emit(self) -> None:
        # Populating the controls fires their signals; without this guard the screen
        # would emit a config change for every widget it builds at startup.
        if self._loading:
            return
        self.config = Config(
            camera_index=self.camera.currentData() or 0,
            mirror=self.mirror.isChecked(),
            sensitivity=self.sensitivity.slider.value() / 100,
            react_after_seconds=self.reaction.slider.value() / 10,
            alerts_enabled=self.alerts_enabled.isChecked(),
            toast_after_seconds=float(self.toast_after.slider.value()),
            dim_enabled=self.dim_enabled.isChecked(),
            dim_after_seconds=float(self.dim_after.slider.value()),
            dim_max_opacity=self.dim_opacity.slider.value() / 100,
            snooze_minutes=self.snooze_minutes.value(),
            breaks_enabled=self.breaks_enabled.isChecked(),
            break_interval_minutes=self.break_interval.value(),
            start_minimized=self.config.start_minimized,
            launch_at_login=self.config.launch_at_login,
        )
        self.changed.emit(self.config)

    def refresh(self) -> None:
        baseline = Baseline.load(paths.baseline_path())
        if baseline is None:
            self._baseline_note.setText(
                "No baseline yet. The Live screen will capture one the first time it sees you."
            )
            return
        captured = baseline.captured_at.replace("T", " ") or "an unknown time"
        measured = ", ".join(sorted(baseline.values)) or "nothing"
        self._baseline_note.setText(
            f"Captured {captured} from {baseline.sample_count} frames.\nMeasuring: {measured}."
        )
