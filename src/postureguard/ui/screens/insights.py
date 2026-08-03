"""Insights: ask a question about your posture history, answered by the Claude API.

Read-only over the same aggregates History already shows. Never touches the live
detection loop, the camera, or the rules engine — the only network call this screen
can trigger is an explicit, user-initiated question.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QVBoxLayout, QWidget
from PySide6.QtCore import Signal

from ... import theme
from ...ai.weekly_summary import build_stats_payload
from ...session import SessionStore
from ..widgets import Card, PageHeader, button, label, plain

S = theme.SPACE
#: Wider than the weekly summary's 7 days — Insights is for "what's been going on
#: lately," not just last week.
INSIGHTS_DAYS = 90


class InsightsScreen(QWidget):
    #: Carries the question text; the app owns the actual API call so this widget
    #: never imports the network client itself.
    asked = Signal(str)

    def __init__(self, store: SessionStore) -> None:
        super().__init__()
        self.store = store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(S["xl"], S["xl"], S["xl"], S["xl"])
        layout.setSpacing(S["lg"])
        layout.addWidget(PageHeader("Insights", "Ask a question about your posture history."))

        card = Card("Ask")
        row = QHBoxLayout()
        self.question = QLineEdit()
        self.question.setPlaceholderText("e.g. why do I slouch more after 2pm?")
        self.question.returnPressed.connect(self._ask)
        row.addWidget(self.question, 1)
        self.ask_button = button("Ask")
        self.ask_button.clicked.connect(self._ask)
        row.addWidget(self.ask_button)
        card.add(plain(row))

        self.answer = label("", "Body")
        self.answer.setWordWrap(True)
        card.add(self.answer)
        layout.addWidget(card)
        layout.addStretch(1)

    def _ask(self) -> None:
        text = self.question.text().strip()
        if not text:
            return
        self.asked.emit(text)

    def stats_payload(self) -> dict | None:
        return build_stats_payload(self.store, days=INSIGHTS_DAYS)

    def _set_ready(self, ready: bool) -> None:
        self.ask_button.setEnabled(ready)
        self.question.setEnabled(ready)

    def show_asking(self) -> None:
        self._set_ready(False)
        self.answer.setText("Thinking…")

    def show_answer(self, text: str | None) -> None:
        self._set_ready(True)
        self.answer.setText(
            text
            if text is not None
            else "Couldn't reach the API. Check the key in Settings and try again."
        )

    def show_no_key(self) -> None:
        self.answer.setText("Add an API key in Settings → AI features to use Insights.")
