"""Live monitor: the camera view, the current correction, and today's numbers."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ... import render, theme
from ...rules import FaultKind, Thresholds
from ...session import SessionStore
from ..controller import LiveState
from ..widgets import Card, PageHeader, StatTile, button, eyebrow, label, plain

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
        if state is not None and state.paused:
            # Distinct from the camera-lost message: this is expected behaviour, not
            # a problem to fix, so it says why and how to end it rather than telling
            # the user to check a device that is fine.
            self._note(
                painter, rect,
                "Paused — no activity detected.\nMove the mouse or unlock to resume.",
            )
            self._frame(painter, rect)
            painter.end()
            return

        if state is not None and not state.camera_healthy:
            self._note(
                painter, rect,
                "Camera disconnected — trying to reconnect.\nNothing is being monitored.",
            )
            self._frame(painter, rect)
            painter.end()
            return

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
        # The band marks where the ears sit relative to a *sitting* baseline; standing
        # moves the whole frame geometry, so drawing it here would show a stale line
        # in the wrong place rather than nothing.
        if reading.baseline is not None and reading.status != "standing":
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
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
            text,
        )


class CorrectionCard(Card):
    """What to do right now. The single most important thing on the screen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.setMinimumHeight(150)

        self._eyebrow = eyebrow("Correction")
        self.add(self._eyebrow)

        # The statement is centred in whatever height the card is given. Pinned to the
        # top it left a large void underneath that read as an unfinished layout; centred,
        # the space around it reads as deliberate breathing room for the one thing on
        # this screen the user is meant to act on.
        self.add_stretch()

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

        if state.paused:
            self._show(
                "Paused",
                "No activity detected, so monitoring stopped and the camera was "
                "released. Move the mouse or unlock to resume.",
                theme.MUTED,
                "Status",
            )
            return

        if not state.camera_healthy:
            # Named as a setup problem, not a posture one, and explicit that monitoring
            # has stopped — the failure this screen must never hide.
            self._show(
                "Camera disconnected",
                "Reconnect the camera or pick another in Settings. "
                "Nothing is being monitored until it returns.",
                theme.WARNING,
                "Status",
            )
            return

        if state.calibrating:
            self._show("Calibrating", reading.message or "Hold still.", theme.MUTED, "Setup")
            return
        if not reading.metrics.any_available():
            self._show("No subject", "Step into view to resume monitoring.", theme.MUTED, "Status")
            return
        if reading.status == "snoozed":
            self._show("Snoozed", "Alerts are paused. Monitoring continues.", theme.MUTED, "Status")
            return
        if reading.status == "standing":
            self._show(
                "Standing",
                "Your sitting baseline doesn't apply here, so nothing is being "
                "checked until you sit back down.",
                theme.MUTED,
                "Status",
            )
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

    # Notes are kept to one line at the column width. A note that wraps makes its own
    # tile taller and knocks the whole row's values off a shared baseline.
    COLUMNS = (
        ("gap", "head_shoulder_gap", "{:.2f}", "ear-to-shoulder / width"),
        ("face", "face_scale", "{:.2f}", "face size / width"),
        ("tilt", "eye_roll", "{:+.0f}°", "head roll from level"),
        ("sink", "shoulder_height", "{:.2f}", "shoulder height"),
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
    mini_toggled = Signal()

    def __init__(self, thresholds: Thresholds, store: SessionStore) -> None:
        super().__init__()
        self.store = store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(S["xl"], S["xl"], S["xl"], S["xl"])
        layout.setSpacing(S["lg"])

        header = PageHeader("Live monitor", "Your posture, measured against your own baseline.")
        self._mini = button("Mini window")
        self._mini.clicked.connect(self.mini_toggled)
        header.add_action(self._mini)
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

        # The correction takes the slack rather than a trailing spacer. Pinning both
        # cards to their content left a tall void under them beside a 490px video,
        # which read as a layout that had run out of things to say.
        self.correction = CorrectionCard()
        side.addWidget(self.correction, 1)

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
        side.addWidget(today, 0)

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

    def set_mini_shown(self, shown: bool) -> None:
        """Keep the button naming the action it performs, not the current state."""
        self._mini.setText("Hide mini window" if shown else "Mini window")

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
