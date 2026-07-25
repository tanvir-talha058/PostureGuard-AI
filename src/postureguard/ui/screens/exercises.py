"""Exercises: a routine chosen by what has actually been going wrong.

The screen opens with *why these exercises*, not with the exercises. A drill you
understand the reason for is one you might actually do; a list of stretches is wallpaper.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ... import theme
from ...rules import FAULT_TITLES
from ...session import SessionStore
from ...stretches import ALL_EXERCISES, Exercise, Routine, routine_for
from ..widgets import Card, PageHeader, button, eyebrow, label, plain

S = theme.SPACE


def _mmss(seconds: int) -> str:
    minutes, remainder = divmod(max(seconds, 0), 60)
    return f"{minutes}:{remainder:02d}"


class ExerciseCard(Card):
    """One drill: what it is for, then how to do it."""

    started = Signal(object)

    def __init__(self, exercise: Exercise, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.exercise = exercise
        # Hug the content. In a stacked list the trailing spacer should absorb the
        # slack; without this the cards share it out and each grows a dead band under
        # its own Start button.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)

        top = QHBoxLayout()
        top.setSpacing(S["sm"])
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(label(exercise.name, "CardTitle"))
        purpose = label(exercise.purpose, "Body")
        purpose.setWordWrap(True)
        heading.addWidget(purpose)
        top.addLayout(heading, 1)

        duration = label(f"{exercise.seconds}s", "MetricUnit")
        duration.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        top.addWidget(duration)
        self.add(plain(top))

        # One block at a tight internal rhythm, not one card-body child per step.
        # At the card's 12px body spacing a four-step routine ran to 480px, which
        # reads as four unrelated statements rather than one sequence.
        steps = QVBoxLayout()
        steps.setContentsMargins(0, S["xs"], 0, 0)
        steps.setSpacing(7)
        for index, step in enumerate(exercise.steps, start=1):
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(S["md"])
            # Numbered because these genuinely are a sequence — the order is the
            # instruction, not decoration.
            number = label(f"{index}", "Eyebrow")
            number.setFixedWidth(12)
            # Nudged down to sit on the first text line's baseline; the eyebrow is a
            # smaller face, so top-aligning the boxes leaves the digit visibly high.
            number.setContentsMargins(0, 3, 0, 0)
            number.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
            row.addWidget(number)
            text = label(step, "Body")
            text.setWordWrap(True)
            row.addWidget(text, 1)
            steps.addLayout(row)
        self.add(plain(steps))

        start = button("Start")
        start.clicked.connect(lambda: self.started.emit(self.exercise))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(start)
        self.add(plain(row))


class GuidedTimer(Card):
    """Counts one exercise down, so the user is not also watching a clock."""

    finished = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self._remaining = 0
        self._exercise: Exercise | None = None

        self._eyebrow = eyebrow("In progress")
        self.add(self._eyebrow)
        self._name = label("", "PageTitle")
        self.add(self._name)
        self._clock = label("0:00", "Metric")
        self.add(self._clock)
        self._step = label("", "Body")
        self._step.setWordWrap(True)
        self.add(self._step)

        row = QHBoxLayout()
        row.addStretch(1)
        stop = button("Stop")
        stop.clicked.connect(self.stop)
        row.addWidget(stop)
        self.add(plain(row))

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self.setVisible(False)

    def start(self, exercise: Exercise) -> None:
        self._exercise = exercise
        self._remaining = exercise.seconds
        self._name.setText(exercise.name)
        self._step.setText(exercise.steps[0])
        self._clock.setText(_mmss(self._remaining))
        self.setVisible(True)
        self._timer.start()

    def _tick(self) -> None:
        self._remaining -= 1
        self._clock.setText(_mmss(self._remaining))

        # Walk the steps evenly across the duration rather than dumping all four at
        # once — the point of a guided timer is to be told what to do *now*.
        if self._exercise is not None and self._exercise.steps:
            elapsed = self._exercise.seconds - self._remaining
            per_step = max(self._exercise.seconds / len(self._exercise.steps), 1)
            index = min(int(elapsed / per_step), len(self._exercise.steps) - 1)
            self._step.setText(self._exercise.steps[index])

        if self._remaining <= 0:
            self.stop()
            self.finished.emit()

    def stop(self) -> None:
        self._timer.stop()
        self.setVisible(False)


class ExercisesScreen(QWidget):
    break_taken = Signal()

    def __init__(self, store: SessionStore) -> None:
        super().__init__()
        self.store = store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(S["xl"], S["xl"], S["xl"], S["xl"])
        layout.setSpacing(S["lg"])

        header = PageHeader("Exercises", "Chosen from what your posture has actually been doing.")
        self._show_all = button("Show all")
        self._show_all.clicked.connect(self._toggle_all)
        header.add_action(self._show_all)
        layout.addWidget(header)

        self.timer = GuidedTimer()
        self.timer.finished.connect(self._on_finished)
        layout.addWidget(self.timer)

        self.reason = Card("Why these")
        self._reason_text = label("", "Body")
        self._reason_text.setWordWrap(True)
        self.reason.add(self._reason_text)
        layout.addWidget(self.reason)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # Content must reflow to the available width; a horizontal scrollbar
        # here means a control has escaped the layout, not that the user should scroll.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_host = QWidget()
        self._list = QVBoxLayout(self._list_host)
        self._list.setContentsMargins(0, 0, S["sm"], 0)
        self._list.setSpacing(S["md"])
        scroll.setWidget(self._list_host)
        layout.addWidget(scroll, 1)

        self._showing_all = False
        self.refresh()

    def _toggle_all(self) -> None:
        self._showing_all = not self._showing_all
        self._show_all.setText("Show recommended" if self._showing_all else "Show all")
        self.refresh()

    def refresh(self) -> None:
        dominant = self.store.dominant_fault(days=7)
        if self._showing_all:
            self._reason_text.setText(
                "Every routine in the library. The recommended view narrows this to what "
                "your own history says you need."
            )
            self._populate(ALL_EXERCISES)
            return

        routine: Routine = routine_for(dominant)
        detail = (
            f" Over the last week that has been your most frequent fault"
            f" ({FAULT_TITLES.get(dominant, '').lower()})."
            if dominant
            else ""
        )
        self._reason_text.setText(routine.reason + detail)
        self._populate(routine.exercises)

    def _populate(self, exercises) -> None:
        while self._list.count():
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        for exercise in exercises:
            card = ExerciseCard(exercise)
            card.started.connect(self.timer.start)
            self._list.addWidget(card)
        self._list.addStretch(1)

    def _on_finished(self) -> None:
        self.break_taken.emit()
