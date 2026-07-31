"""The Calibration card: profile picker, baseline status, recalibrate."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QInputDialog

from .... import paths
from ....calibration import Baseline
from ....metrics import describe
from ....monitor_profile import MonitorProfiles, fingerprint
from ...widgets import Card, button, label, plain
from .rows import Row


def _current_arrangement() -> str:
    """A fingerprint of whatever monitors are connected right now."""
    screens = [
        (screen.name(), screen.size().width(), screen.size().height())
        for screen in QGuiApplication.screens()
    ]
    return fingerprint(screens)


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


class CalibrationPanel(Card):
    """Profile selection and baseline status. Owns its own refresh on profile change."""

    changed = Signal()
    recalibrate_requested = Signal()

    def __init__(
        self,
        calibration_profile: str,
        auto_profile_by_monitor: bool = False,
        monitor_profiles: MonitorProfiles | None = None,
    ) -> None:
        super().__init__(
            "Calibration",
            "Your baseline is what every threshold is measured against. "
            "Recapture it whenever the camera or your chair moves.",
        )
        self._default_profile = calibration_profile
        self.monitor_profiles = monitor_profiles if monitor_profiles is not None else MonitorProfiles()

        self.add(label("Profile", "Eyebrow"))
        self.profile = QComboBox()
        self._reload_profiles(calibration_profile)
        new_profile = button("New…", "Ghost")
        new_profile.clicked.connect(self._create_profile)
        profile_row = QHBoxLayout()
        profile_row.addWidget(self.profile, 1)
        profile_row.addWidget(new_profile)
        self.add(plain(profile_row))

        self._baseline_note = label("", "Body")
        self._baseline_note.setWordWrap(True)
        self.add(self._baseline_note)
        recalibrate = button("Recalibrate now", "Primary")
        recalibrate.clicked.connect(self.recalibrate_requested)
        row = QHBoxLayout()
        row.addWidget(recalibrate)
        row.addStretch(1)
        self.add(plain(row))

        self.auto_by_monitor = QCheckBox("Enabled")
        self.auto_by_monitor.setChecked(auto_profile_by_monitor)
        self.add(
            Row(
                "Auto-switch by monitor setup",
                "Switch profiles on its own when it recognizes the connected "
                "monitors — remember a setup below, once per profile.",
                self.auto_by_monitor,
            )
        )
        remember = button("Remember this setup…", "Ghost")
        remember.clicked.connect(self._remember_current_setup)
        remember_row = QHBoxLayout()
        remember_row.addWidget(remember)
        remember_row.addStretch(1)
        self.add(plain(remember_row))
        self._monitor_note = label("", "Eyebrow")
        self.add(self._monitor_note)

        self.auto_by_monitor.toggled.connect(self.changed)
        self.profile.currentTextChanged.connect(self._on_profile_changed)
        self.refresh()

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
        self.refresh()
        self.changed.emit()

    def _remember_current_setup(self) -> None:
        """Associate the monitors connected right now with the selected profile."""
        key = _current_arrangement()
        self.monitor_profiles.remember(key, self.profile.currentText())
        self.monitor_profiles.save(paths.monitor_profiles_path())
        self._monitor_note.setText(f'Remembered this monitor setup for "{self.profile.currentText()}".')

    def refresh(self) -> None:
        active_profile = self.profile.currentText() or self._default_profile
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
