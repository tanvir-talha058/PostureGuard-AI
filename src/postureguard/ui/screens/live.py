"""Live monitor: the camera view, the current correction, and today's numbers."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ... import render, theme
from ...rules import FaultKind, Thresholds
from ...session import SessionStore
from ..controller import LiveState
from ..widgets import Card, StatTile, PageHeader, button, eyebrow, label, plain

S = theme.SPACE


class VideoView(QWidget):
    """The camera feed with the posture guides drawn over it.

    The guides are the reason this view is large here rather than a thumbnail: the
    tolerance band only teaches you where to move if you can see where your ears sit
    relative to it.
    """

    def __init__(self, thresholds: Thresholds, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.thresholds = thresholds
        self.state: LiveState | None = None
        self.setMinimumSize(420, 320)
        self.setSizePolicy(self.sizePolicy().horizontalPolicy(), self.sizePolicy().verticalPolicy())

    def set_state(self, state: LiveState) -> None:
        self.state = state
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())

        painter.fillRect(rect, QColor("#0C0E12"))

        state = self.state
        if state is None or state.frame is None:
            self._note(painter, rect, "Waiting for camera")
            self._frame(painter, rect)
            painter.end()
            return

        transform = render.draw_video(painter, state.frame, rect)
        reading = state.reading

        if reading.landmarks is None or not reading.metrics.any_available():
            self._note(painter, rect, reading.message or "Step into view")
            self._frame(painter, rect)
            painter.end()
            return

        faulty = frozenset(j for fault in reading.faults for j in fault.joints)
        accent = theme.STATE_COLORS.get(reading.status, theme.MUTED)

        render.draw_plumb_line(painter, reading.landmarks, transform)
        if reading.baseline is not None:
            render.draw_tolerance_band(
                painter,
                reading.landmarks,
                transform,
                reading.baseline,
                self.thresholds,
                state.aspect,
                in_tolerance=not reading.faults,
            )
        render.draw_skeleton(painter, reading.landmarks, transform, faulty, accent)
        self._frame(painter, rect)
        painter.end()

    def _frame(self, painter: QPainter, rect: QRectF) -> None:
        pen = QPen(theme.RULE)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

    def _note(self, painter: QPainter, rect: QRectF, text: str) -> None:
        painter.setFont(theme.cue_font())
        painter.setPen(theme.with_alpha(theme.BONE, 190))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)


class CorrectionCard(Card):
    """What to do right now. The single most important thing on the screen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setMinimumHeight(150)

        self._eyebrow = eyebrow("Correction")
        self.add(self._eyebrow)

        self._title = label("In tolerance", "PageTitle")
        self._title.setWordWrap(True)
        self.add(self._title)

        self._cue = label("Nothing to change. Keep going.", "Body")
        self._cue.setWordWrap(True)
        self.add(self._cue)

        self._extra = label("", "Eyebrow")
        self._extra.setVisible(False)
        self.add(self._extra)
        self.add_stretch()

    def set_reading(self, state: LiveState) -> None:
        reading = state.reading

        if state.calibrating:
            self._show("Calibrating", reading.message or "Hold still.", theme.MUTED, "Setup")
            return
        if not reading.metrics.any_available():
            self._show("No subject", "Step into view to resume monitoring.", theme.MUTED, "Status")
            return
        if reading.status == "snoozed":
            self._show("Snoozed", "Alerts are paused. Monitoring continues.", theme.MUTED, "Status")
            return

        actionable = [f for f in reading.faults if f.kind is not FaultKind.DRIFT]
        if not actionable:
            drift = next((f for f in reading.faults if f.kind is FaultKind.DRIFT), None)
            if drift is not None:
                self._show("Drifting", drift.cue, theme.WARNING, "Correction")
                return
            self._show("In tolerance", "Nothing to change. Keep going.", theme.IN_TOLERANCE, "Status")
            return

        primary = actionable[0]
        self._show(primary.title, primary.cue, theme.FAULT, "Correction")
        others = len(actionable) - 1
        if others:
            self._extra.setText(f"+{others} MORE ACTIVE")
            self._extra.setVisible(True)

    def _show(self, title: str, cue: str, colour: QColor, eyebrow_text: str) -> None:
        self._eyebrow.setText(eyebrow_text.upper())
        self._title.setText(title)
        self._title.setStyleSheet(f"color: {colour.name()};")
        self._cue.setText(cue)
        self._extra.setVisible(False)


class ReadingsStrip(QWidget):
    """The raw measurements, for anyone who wants to see the instrument working."""

    COLUMNS = (
        ("gap", "head_shoulder_gap", "{:.2f}", "ear-to-shoulder, over shoulder width"),
        ("face", "face_scale", "{:.2f}", "face size, over shoulder width"),
        ("tilt", "eye_roll", "{:+.0f}°", "head roll from level"),
        ("sink", "shoulder_height", "{:.2f}", "shoulder height in frame"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(S["xl"])

        self._tiles: dict[str, StatTile] = {}
        for caption, field, _, note in self.COLUMNS:
            tile = StatTile(caption, "—", note=note)
            self._tiles[field] = tile
            layout.addWidget(tile, 1)

    def set_metrics(self, state: LiveState) -> None:
        values = state.reading.metrics.as_dict()
        for _, field, fmt, _ in self.COLUMNS:
            value = values.get(field)
            self._tiles[field].set_value(fmt.format(value) if value is not None else "—")


def _duration(seconds: float) -> str:
    seconds = max(int(seconds), 0)
    hours, remainder = divmod(seconds, 3600)
    minutes = remainder // 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


class LiveScreen(QWidget):
    """Camera, correction, and today's standing."""

    snooze_requested = Signal()
    recalibrate_requested = Signal()

    def __init__(self, thresholds: Thresholds, store: SessionStore) -> None:
        super().__init__()
        self.store = store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(S["xl"], S["xl"], S["xl"], S["xl"])
        layout.setSpacing(S["lg"])

        header = PageHeader("Live monitor", "Your posture, measured against your own baseline.")
        self._snooze = button("Snooze")
        self._snooze.clicked.connect(self.snooze_requested)
        header.add_action(self._snooze)
        recalibrate = button("Recalibrate")
        recalibrate.clicked.connect(self.recalibrate_requested)
        header.add_action(recalibrate)
        layout.addWidget(header)

        body = QHBoxLayout()
        body.setSpacing(S["lg"])
        layout.addLayout(body, 1)

        self.video = VideoView(thresholds)
        body.addWidget(self.video, 3)

        side = QVBoxLayout()
        side.setSpacing(S["lg"])
        body.addLayout(side, 2)

        self.correction = CorrectionCard()
        side.addWidget(self.correction)

        today = Card("Today")
        grid = QGridLayout()
        grid.setSpacing(S["lg"])
        self.score_tile = StatTile("posture score", "—", "%")
        self.tracked_tile = StatTile("time at desk", "—")
        self.session_tile = StatTile("this session", "—")
        self.break_tile = StatTile("next break", "—")
        # Top-aligned, so a tile that grows a note does not shove its neighbours out
        # of line and break the row's shared baseline.
        top = Qt.AlignmentFlag.AlignTop
        grid.addWidget(self.score_tile, 0, 0, top)
        grid.addWidget(self.tracked_tile, 0, 1, top)
        grid.addWidget(self.session_tile, 1, 0, top)
        grid.addWidget(self.break_tile, 1, 1, top)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        today.add(plain(grid))
        side.addWidget(today)
        side.addStretch(1)

        readings = Card("Measurements", "The numbers the decisions are made from.")
        self.readings = ReadingsStrip()
        readings.add(self.readings)
        layout.addWidget(readings)

        self._since_refresh = 0.0

    def on_state(self, state: LiveState) -> None:
        self.video.set_state(state)
        self.correction.set_reading(state)
        self.readings.set_metrics(state)

        self.session_tile.set_value(_duration(state.session_seconds))
        self.break_tile.set_value(
            "—" if state.seconds_until_break <= 0 else _duration(state.seconds_until_break)
        )
        self._snooze.setText("Snoozed" if state.reading.status == "snoozed" else "Snooze")

        # Today's totals come from SQLite; re-querying every frame would hammer the
        # database for a number that changes once a second at most.
        if state.session_seconds - self._since_refresh >= 5.0:
            self._since_refresh = state.session_seconds
            self.refresh()

    def refresh(self) -> None:
        summary = self.store.today()
        if summary.tracked_seconds == 0:
            self.score_tile.set_value("—", note="Nothing tracked yet")
            self.tracked_tile.set_value("—")
            return
        self.score_tile.set_value(f"{summary.score:.0f}", note="")
        self.score_tile.set_tone(
            "StatusGood" if summary.score >= 80
            else "StatusWarn" if summary.score >= 60
            else "StatusFault"
        )
        self.tracked_tile.set_value(_duration(summary.tracked_seconds))
