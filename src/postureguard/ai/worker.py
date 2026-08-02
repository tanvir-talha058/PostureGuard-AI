"""A tiny QThread wrapper so AI network calls never run on the UI thread.

Every AI feature here is either a background job (weekly summary) or an on-demand
user action (Insights, exercise context, regenerating cue phrasings); none of them
may block the Qt event loop for the seconds an API round trip can take.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QThread, Signal


class AskWorker(QThread):
    """Runs one no-argument callable on a background thread and reports its result."""

    finished_with = Signal(object)

    def __init__(self, work: Callable[[], object], parent=None) -> None:
        super().__init__(parent)
        self._work = work

    def run(self) -> None:
        try:
            result = self._work()
        except Exception:  # noqa: BLE001 - a background thread must never crash
            # the app; every caller already treats None as "this failed."
            result = None
        self.finished_with.emit(result)
