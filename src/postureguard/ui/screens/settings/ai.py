"""The AI card: opt-in Claude-API-backed features, and the one key they all share."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QCheckBox, QLineEdit

from ...widgets import Card, button, label
from .rows import Row


class AiPanel(Card):
    changed = Signal()
    regenerate_cue_variants_requested = Signal()

    def __init__(self, config) -> None:
        super().__init__("AI features")
        self.add(
            label(
                "Off by default. Each toggle below sends only aggregate numbers — "
                "never video or images — to Anthropic's API when it fires.",
                "Body",
            )
        )

        self.api_key = QLineEdit(config.ai_api_key)
        self.api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key.setPlaceholderText("sk-ant-…")
        self.add(Row("Anthropic API key", "Required by every toggle below.", self.api_key))

        self.weekly_summary = QCheckBox("Enabled")
        self.weekly_summary.setChecked(config.ai_weekly_summary_enabled)
        self.add(
            Row(
                "AI weekly summary",
                "A richer weekly note, sent your daily scores, worst hour, and fault "
                "minutes for the week.",
                self.weekly_summary,
            )
        )

        self.insights = QCheckBox("Enabled")
        self.insights.setChecked(config.ai_insights_enabled)
        self.add(
            Row(
                "Insights screen",
                "Ask questions about your history. Sends your question and the same "
                "aggregates as the weekly summary.",
                self.insights,
            )
        )

        self.cue_variants = QCheckBox("Enabled")
        self.cue_variants.setChecked(config.ai_cue_variants_enabled)
        self.add(
            Row(
                "Varied correction phrasing",
                "Alternate wordings of the fixed correction text, regenerated at most "
                "once a day.",
                self.cue_variants,
            )
        )
        self.regenerate = button("Regenerate phrasings now")
        self.regenerate.clicked.connect(self.regenerate_cue_variants_requested)
        self.add(Row("", "Uses today's key and toggle above.", self.regenerate))

        self.exercise_context = QCheckBox("Enabled")
        self.exercise_context.setChecked(config.ai_exercise_context_enabled)
        self.add(
            Row(
                "Exercise context",
                "A short AI-written note on why this routine, added above the fixed "
                "exercise list. Never changes which exercises appear.",
                self.exercise_context,
            )
        )

        self.api_key.editingFinished.connect(self.changed)
        self.weekly_summary.toggled.connect(self.changed)
        self.insights.toggled.connect(self.changed)
        self.cue_variants.toggled.connect(self.changed)
        self.exercise_context.toggled.connect(self.changed)
