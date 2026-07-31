"""The Calibration card: profile picker, baseline status, recalibrate."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QInputDialog

from .... import paths
from ....calibration import Baseline
from ....metrics import describe
from ...widgets import Card, button, label, plain


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

    def __init__(self, calibration_profile: str) -> None:
        super().__init__(
            "Calibration",
            "Your baseline is what every threshold is measured against. "
            "Recapture it whenever the camera or your chair moves.",
        )
        self._default_profile = calibration_profile

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
