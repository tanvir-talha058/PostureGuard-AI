"""The Startup and Appearance cards — small enough to share one module."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QComboBox

from ...widgets import Card
from .rows import Row


class StartupPanel(Card):
    changed = Signal()

    def __init__(self, config) -> None:
        super().__init__("Startup")

        self.launch_at_login = QCheckBox("Enabled")
        self.launch_at_login.setChecked(config.launch_at_login)
        self.add(
            Row(
                "Launch at login",
                "Start PostureGuard automatically when you sign in to Windows.",
                self.launch_at_login,
            )
        )

        self.start_minimized = QCheckBox("Enabled")
        self.start_minimized.setChecked(config.start_minimized)
        self.add(
            Row(
                "Start minimized",
                "Come up in the tray rather than opening the main window.",
                self.start_minimized,
            )
        )

        self.launch_at_login.toggled.connect(self.changed)
        self.start_minimized.toggled.connect(self.changed)


class AppearancePanel(Card):
    changed = Signal()

    def __init__(self, config) -> None:
        super().__init__("Appearance")

        self.theme_mode = QComboBox()
        self.theme_mode.addItem("Dark", "dark")
        self.theme_mode.addItem("Light", "light")
        index = self.theme_mode.findData(config.theme_mode)
        self.theme_mode.setCurrentIndex(index if index >= 0 else 0)
        self.add(Row("Theme", "The instrument palette, dark or light.", self.theme_mode))

        self.theme_mode.currentIndexChanged.connect(self.changed)
