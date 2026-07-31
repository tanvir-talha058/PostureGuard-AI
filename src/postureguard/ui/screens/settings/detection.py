"""The Detection card: sensitivity, patience, camera, mirroring, standing detection."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox

from ...widgets import Card
from .rows import Row, SliderRow


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


class DetectionPanel(Card):
    changed = Signal()

    def __init__(self, config, cameras: list | None = None) -> None:
        super().__init__("Detection")

        self.sensitivity = SliderRow(
            "Sensitivity",
            "How far you have to stray from your baseline before it counts.",
            25, 200, int(config.sensitivity * 100), _sensitivity_words,
        )
        self.add(self.sensitivity)

        self.reaction = SliderRow(
            "Patience",
            "How long bad posture must hold before it is called a fault. "
            "Shorter catches more; longer ignores fidgeting.",
            2, 40, int(config.react_after_seconds * 10),
            lambda v: f"{v / 10:.1f}s",
        )
        self.add(self.reaction)

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
        self.add(
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
        self.add(
            Row("Mirroring", "Makes the view behave like a mirror, which is easier to correct against.", self.mirror)
        )

        self.standing_detection = QCheckBox("Enabled")
        self.standing_detection.setChecked(config.standing_detection_enabled)
        self.add(
            Row(
                "Standing detection",
                "Pause checks while you're standing — your sitting baseline "
                "doesn't apply, so guessing would be worse than not checking.",
                self.standing_detection,
            )
        )

        self.sensitivity.slider.valueChanged.connect(self.changed)
        self.reaction.slider.valueChanged.connect(self.changed)
        self.camera.currentIndexChanged.connect(self.changed)
        self.mirror.toggled.connect(self.changed)
        self.standing_detection.toggled.connect(self.changed)
