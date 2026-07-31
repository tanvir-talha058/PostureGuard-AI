"""The Interventions card: the escalation ladder's timing and on/off switches."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QSpinBox

from ...widgets import Card
from .rows import Row, SliderRow


class InterventionsPanel(Card):
    changed = Signal()

    def __init__(self, config) -> None:
        super().__init__(
            "Interventions",
            "The overlay cue is always on. These control what happens when it is ignored.",
        )

        self.mini_window = QCheckBox("Enabled")
        self.mini_window.setChecked(config.mini_window)
        self.add(
            Row(
                "Mini window",
                "A small readout showing live posture and the current fix. Drag it "
                "anywhere; double-click to collapse it to a single line.",
                self.mini_window,
            )
        )

        self.mini_always_on_top = QCheckBox("Always on top")
        self.mini_always_on_top.setChecked(config.mini_always_on_top)
        self.add(
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
        self.add(Row("Notifications", "A prompt naming the fault and the fix.", self.alerts_enabled))

        self.suppress_when_fullscreen = QCheckBox("Enabled")
        self.suppress_when_fullscreen.setChecked(config.suppress_when_fullscreen)
        self.add(
            Row(
                "Hold back during fullscreen",
                "Skip the notification and screen dimming while presenting, on a "
                "call, or in a game. The overlay cue stays on.",
                self.suppress_when_fullscreen,
            )
        )

        self.alert_sound = QCheckBox("Enabled")
        self.alert_sound.setChecked(config.alert_sound_enabled)
        self.add(
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
        self.add(self.toast_after)

        self.dim_enabled = QCheckBox("Enabled")
        self.dim_enabled.setChecked(config.dim_enabled)
        self.add(
            Row("Screen dimming", "The last rung. Fades in gradually and never blocks clicks.", self.dim_enabled)
        )

        self.dim_after = SliderRow(
            "Dim after",
            "Time from the fault starting to the screen beginning to dim.",
            20, 300, int(config.dim_after_seconds), lambda v: f"{v}s",
        )
        self.add(self.dim_after)

        self.dim_opacity = SliderRow(
            "Maximum dim",
            "How dark it gets at full escalation.",
            10, 80, int(config.dim_max_opacity * 100), lambda v: f"{v}%",
        )
        self.add(self.dim_opacity)

        self.hotkeys_enabled = QCheckBox("Enabled")
        self.hotkeys_enabled.setChecked(config.hotkeys_enabled)
        self.add(
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
        self.add(Row("Snooze length", "How long the Snooze button silences alerts for.", self.snooze_minutes))

        for check in (
            self.mini_window, self.mini_always_on_top, self.alerts_enabled,
            self.suppress_when_fullscreen, self.alert_sound, self.dim_enabled,
            self.hotkeys_enabled,
        ):
            check.toggled.connect(self.changed)
        for slider_row in (self.toast_after, self.dim_after, self.dim_opacity):
            slider_row.slider.valueChanged.connect(self.changed)
        self.snooze_minutes.valueChanged.connect(self.changed)
