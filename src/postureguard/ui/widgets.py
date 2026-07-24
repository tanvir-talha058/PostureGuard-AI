"""Reusable building blocks shared across the four screens.

Composed rather than styled ad hoc: a card is a Card everywhere, an eyebrow is the same
9px tracked mono everywhere. Consistency here is what stops four screens built at four
different moments from looking like four different applications.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import theme

S = theme.SPACE


#: Roles that hold prose. An unwrapped prose label reports its entire single-line width
#: as a layout minimum, which silently widens whatever contains it — the failure shows
#: up not on the label but as clipped controls elsewhere on the screen. Wrapping by
#: default makes that impossible to reintroduce.
_WRAPPING_ROLES = frozenset({"Body", "PageSubtitle"})


def label(text: str, role: str, parent: QWidget | None = None) -> QLabel:
    """A label carrying one of the type roles defined in the stylesheet."""
    widget = QLabel(text, parent)
    widget.setObjectName(role)
    if role in _WRAPPING_ROLES:
        widget.setWordWrap(True)
        # A wrapped QLabel does not tell its layout that its height depends on its
        # width unless the size policy says so. Without this, Qt sizes it from a
        # guessed width and reserves two or three lines for text that occupies one —
        # which is where the app's excess vertical space was coming from.
        policy = widget.sizePolicy()
        policy.setHeightForWidth(True)
        policy.setVerticalPolicy(QSizePolicy.Policy.Minimum)
        widget.setSizePolicy(policy)
    return widget


def eyebrow(text: str) -> QLabel:
    return label(text.upper(), "Eyebrow")


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.HLine)
    line.setFixedHeight(1)
    return line


def spacer(width: int = 0, height: int = 0) -> QWidget:
    widget = QWidget()
    widget.setFixedSize(max(width, 0), max(height, 0))
    if width == 0:
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return widget


def crisp(value: float) -> float:
    """Snap a coordinate to a half-pixel so a 1px stroke lands on one pixel.

    Qt centres a stroke on its path. A 1px line drawn at an integer coordinate with
    antialiasing on therefore straddles two pixel rows and renders as two grey lines
    instead of one solid one — the single most common reason a dark UI looks soft.
    """
    return round(value) + 0.5


def plain(layout) -> QWidget:
    """A layout container that does not paint.

    A bare QWidget inherits the window ground, so dropping one inside a Card stamps an
    opaque ink rectangle over the card surface. Every grouping container goes through
    here so that cannot happen by accident.
    """
    holder = QWidget()
    holder.setObjectName("Plain")
    holder.setLayout(layout)
    return holder


def button(text: str, variant: str = "Secondary") -> QPushButton:
    widget = QPushButton(text)
    widget.setObjectName(variant)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    return widget


class Card(QFrame):
    """A titled surface. The unit every screen is assembled from."""

    def __init__(
        self,
        title: str = "",
        subtitle: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Card")

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(S["lg"], S["lg"], S["lg"], S["lg"])
        self._outer.setSpacing(S["md"])

        self.header = QHBoxLayout()
        self.header.setSpacing(S["sm"])
        if title:
            heading = QVBoxLayout()
            heading.setSpacing(2)
            heading.addWidget(label(title, "CardTitle"))
            if subtitle:
                # Must wrap. An unwrapped subtitle reports its full single-line width as
                # a minimum, which pushes the card past its scroll viewport and clips
                # every control on the right-hand side of the screen.
                caption = label(subtitle, "Body")
                caption.setWordWrap(True)
                heading.addWidget(caption)
            # The heading takes the stretch, not a trailing spacer. With the spacer
            # holding it, a wrapped subtitle collapses to its minimum width and breaks
            # after three or four words.
            self.header.addLayout(heading, 1)
            self._outer.addLayout(self.header)

        self.body = QVBoxLayout()
        self.body.setSpacing(S["md"])
        self._outer.addLayout(self.body)
        self._has_separated_rows = False

    def add(self, widget: QWidget, stretch: int = 0) -> QWidget:
        # Widgets that draw their own separator rule supply their own vertical padding,
        # so the card must not add spacing on top — that would double the gap and leave
        # the rule floating between two blocks instead of dividing them.
        if getattr(widget, "separator", False):
            if not self._has_separated_rows:
                self._has_separated_rows = True
                self.body.setSpacing(0)
                widget.set_first()
        self.body.addWidget(widget, stretch)
        return widget

    def add_header_widget(self, widget: QWidget) -> QWidget:
        self.header.addWidget(widget)
        return widget

    def add_stretch(self) -> None:
        self.body.addStretch(1)


#: Fixed row heights, so a column of tiles shares one baseline whether or not each
#: tile happens to have a note. Letting them size to content is what makes a stat row
#: look subtly crooked — the values drift by a few pixels against each other.
CAPTION_HEIGHT = 13
VALUE_HEIGHT = 38
NOTE_HEIGHT = 17


class StatTile(QWidget):
    """One number, its unit, and what it means.

    The label sits *above* the value. A number you have to read before you know what it
    measures is a number you read twice.

    Every row is a fixed height and the note slot is always reserved, so tiles align to
    a shared grid across a row regardless of what they contain.
    """

    def __init__(
        self,
        caption: str,
        value: str = "—",
        unit: str = "",
        note: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._caption = eyebrow(caption)
        self._caption.setFixedHeight(CAPTION_HEIGHT)
        layout.addWidget(self._caption)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        # Baseline-align the unit to the number rather than centring it, so "%" sits
        # on the digits' baseline the way it would if they were one piece of text.
        row.setAlignment(Qt.AlignmentFlag.AlignBottom)
        self._value = label(value, "Metric")
        self._value.setFixedHeight(VALUE_HEIGHT)
        row.addWidget(self._value)
        self._unit = label(unit, "MetricUnit")
        self._unit.setContentsMargins(0, 0, 0, 7)
        row.addWidget(self._unit)
        row.addStretch(1)
        layout.addLayout(row)

        # Always present, never wrapping. A note that wraps to a second line pushes its
        # own tile taller and breaks the row it belongs to.
        self._note = label(note, "Body")
        self._note.setWordWrap(False)
        self._note.setFixedHeight(NOTE_HEIGHT)
        layout.addWidget(self._note)

    def set_value(self, value: str, unit: str | None = None, note: str | None = None) -> None:
        self._value.setText(value)
        if unit is not None:
            self._unit.setText(unit)
        if note is not None:
            # Elided, not wrapped — the slot is one line tall by construction.
            metrics = self._note.fontMetrics()
            width = max(self._note.width(), 80)
            self._note.setText(
                metrics.elidedText(note, Qt.TextElideMode.ElideRight, width)
            )
            self._note.setToolTip(note if note else "")

    def set_tone(self, role: str) -> None:
        """Recolour the value: StatusGood, StatusWarn, StatusFault, or Metric.

        Colour is applied directly rather than by swapping objectName. Changing the
        object name would move the widget onto a different selector and silently drop
        everything the ``#Metric`` rule provides — font, size, weight — leaving a
        correctly coloured but tiny number.
        """
        colour = {
            "StatusGood": theme.IN_TOLERANCE,
            "StatusWarn": theme.WARNING,
            "StatusFault": theme.FAULT,
        }.get(role, theme.BONE)
        self._value.setStyleSheet(f"color: {colour.name()};")


class EmptyState(QWidget):
    """Shown where data would be, when there is none yet.

    An empty screen is an invitation to act, so these say what will fill the space and
    what to do to make that happen — never just "no data".
    """

    def __init__(self, headline: str, guidance: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(S["xl"], S["2xl"], S["xl"], S["2xl"])
        layout.setSpacing(S["sm"])
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        headline_label = label(headline, "CardTitle")
        headline_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(headline_label)

        guidance_label = label(guidance, "Body")
        guidance_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        guidance_label.setWordWrap(True)
        layout.addWidget(guidance_label)


class PageHeader(QWidget):
    """Title, one line of orientation, and the screen's actions."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S["md"])

        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label(title, "PageTitle"))
        if subtitle:
            text.addWidget(label(subtitle, "PageSubtitle"))
        # Stretch on the text, not on a trailing spacer — otherwise the wrapped
        # subtitle collapses to its minimum width and breaks after a few words.
        layout.addLayout(text, 1)

        self.actions = QHBoxLayout()
        self.actions.setSpacing(S["sm"])
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget


def soften(widget: QWidget, radius: int = 24, alpha: int = 90) -> QWidget:
    """A shadow to lift a surface off the ground. Used sparingly."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(radius)
    effect.setOffset(0, 4)
    effect.setColor(theme.with_alpha(theme.SIDEBAR, alpha))
    widget.setGraphicsEffect(effect)
    return widget
