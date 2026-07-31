"""Shared row widgets used by every settings panel."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QSlider, QVBoxLayout, QWidget

from .... import theme
from ...widgets import crisp, label

S = theme.SPACE


class Row(QWidget):
    """A labelled setting: name, one line of consequence, and the control.

    Rows carry their own top rule and padding rather than relying on the card's
    spacing. Settings cards stack many rows, and without a separator they run
    together into one grey wall of text.
    """

    #: Painted rather than added as a widget, so it spans the full card width and does
    #: not participate in the row's own layout maths.
    separator = True

    def __init__(self, title: str, explanation: str, control: QWidget) -> None:
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, S["md"], 0, S["md"])
        layout.setSpacing(S["lg"])

        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(label(title, "CardTitle"))
        note = label(explanation, "Body")
        note.setWordWrap(True)
        text.addWidget(note)
        layout.addLayout(text, 1)

        # Fixed, not minimum: a minimum lets a long checkbox caption widen the control
        # column until the whole card overflows its scroll area horizontally.
        control.setFixedWidth(210)
        layout.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.control = control
        self._first = False

    def paintEvent(self, event) -> None:
        if self._first:
            return
        painter = QPainter(self)
        pen = QPen(theme.RULE)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        edge = crisp(0, self.devicePixelRatioF())
        painter.drawLine(QPointF(0, edge), QPointF(self.width(), edge))
        painter.end()

    def set_first(self) -> None:
        """The topmost row in a card needs no rule above it."""
        self._first = True
        self.update()


class SliderRow(Row):
    """A slider that always shows what its current position means in words."""

    def __init__(
        self,
        title: str,
        explanation: str,
        minimum: int,
        maximum: int,
        value: int,
        formatter,
    ) -> None:
        holder = QWidget()
        holder.setObjectName("Plain")
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(minimum, maximum)
        self.slider.setValue(value)
        layout.addWidget(self.slider)

        self._readout = label(formatter(value), "Eyebrow")
        self._readout.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(self._readout)

        super().__init__(title, explanation, holder)
        self._formatter = formatter
        self.slider.valueChanged.connect(
            lambda v: self._readout.setText(self._formatter(v))
        )
