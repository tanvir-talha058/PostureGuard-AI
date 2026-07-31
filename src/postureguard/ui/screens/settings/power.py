"""The Power card: camera release on idle/lock and the battery frame-rate cut."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox

from ...widgets import Card
from .rows import Row, SliderRow


class PowerPanel(Card):
    changed = Signal()

    def __init__(self, config) -> None:
        super().__init__(
            "Power",
            "The camera is released — not just idled — while nothing needs watching, "
            "which stops it drawing power and turns its capture light off.",
        )

        self.pause_when_locked = QCheckBox("Enabled")
        self.pause_when_locked.setChecked(config.pause_when_locked)
        self.add(
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
        self.add(self.pause_after_idle)

        self.battery_saver = QCheckBox("Enabled")
        self.battery_saver.setChecked(config.battery_saver)
        self.add(
            Row(
                "Reduce activity on battery",
                "Halves the camera frame rate while unplugged. Detection is unaffected.",
                self.battery_saver,
            )
        )

        self.pause_when_locked.toggled.connect(self.changed)
        self.pause_after_idle.slider.valueChanged.connect(self.changed)
        self.battery_saver.toggled.connect(self.changed)
