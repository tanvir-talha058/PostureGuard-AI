"""The Privacy card: retention, data folder, export and delete."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLineEdit, QMessageBox, QSpinBox

from .... import paths
from ...widgets import Card, button, label, plain
from .rows import Row


class PrivacyPanel(Card):
    changed = Signal()

    def __init__(self, config, store) -> None:
        super().__init__("Privacy")
        self.store = store

        self.add(
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
        self.add(
            Row(
                "Keep history for",
                "History older than this is deleted automatically. The Live screen "
                "and today's stats are never affected.",
                self.retention_days,
            )
        )
        self.add(label("Data folder", "Eyebrow"))
        # A filesystem path is a single unbreakable token, so a wrapped QLabel reports
        # the whole path as its minimum width and drags the entire scroll area wider
        # than its viewport — clipping every control on the right. A read-only field
        # scrolls internally instead, and lets the user copy the path out.
        location = QLineEdit(str(paths.data_dir()))
        location.setReadOnly(True)
        location.setObjectName("PathField")
        location.setCursorPosition(0)
        self.add(location)

        data_actions = QHBoxLayout()
        export_button = button("Export history…", "Secondary")
        export_button.clicked.connect(self._export_history)
        data_actions.addWidget(export_button)
        delete_button = button("Delete all data…", "Secondary")
        delete_button.clicked.connect(self._delete_all_data)
        data_actions.addWidget(delete_button)
        data_actions.addStretch(1)
        self.add(plain(data_actions))

        self.retention_days.valueChanged.connect(self.changed)

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
