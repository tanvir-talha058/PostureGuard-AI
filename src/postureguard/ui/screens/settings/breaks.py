"""The Breaks card: stretch-break reminders and the weekly summary toggle."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QSpinBox

from ...widgets import Card
from .rows import Row


class BreaksPanel(Card):
    changed = Signal()

    def __init__(self, config) -> None:
        super().__init__("Breaks")

        self.breaks_enabled = QCheckBox("Enabled")
        self.breaks_enabled.setChecked(config.breaks_enabled)
        self.add(
            Row("Break reminders", "Counts only time you are actually at the desk.", self.breaks_enabled)
        )

        self.break_interval = QSpinBox()
        self.break_interval.setRange(5, 180)
        self.break_interval.setSuffix(" min")
        self.break_interval.setValue(config.break_interval_minutes)
        self.add(Row("Break interval", "Working time between prompts.", self.break_interval))

        self.weekly_summary_enabled = QCheckBox("Enabled")
        self.weekly_summary_enabled.setChecked(config.weekly_summary_enabled)
        self.add(
            Row(
                "Weekly summary",
                "A once-a-week note naming the hour posture held up worst.",
                self.weekly_summary_enabled,
            )
        )

        self.breaks_enabled.toggled.connect(self.changed)
        self.break_interval.valueChanged.connect(self.changed)
        self.weekly_summary_enabled.toggled.connect(self.changed)
