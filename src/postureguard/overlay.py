"""The always-on-top mini window.

A small frameless panel the user parks in a screen corner. This is the surface that
actually changes posture: the main window is where you go to look at your posture, but
this is what is in front of you at the moment you are getting it wrong.

Deliberately narrow and quiet. Something that sits in peripheral vision for eight hours
cannot afford to be loud, or it gets closed by lunchtime — so it stays calm while you
are fine, and earns attention only as a fault is ignored.

Reading order is fixed and never rearranges — status, view, instruction, readings —
so the eye learns where to look and can check posture in a glance rather than a read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QWidget

from . import render, theme
from .calibration import Baseline
from .landmarks import Landmarks
from .metrics import PostureMetrics
from .rules import Fault, FaultKind, Thresholds

HEADER_HEIGHT = 30
FAULT_HEIGHT = 68
READINGS_HEIGHT = 34
CORNER_RADIUS = 10

STATUS_LABELS = {
    "starting": "STARTING",
    "calibrating": "CALIBRATING",
    "searching": "NO SUBJECT",
    "in_tolerance": "IN TOLERANCE",
    "drifting": "DRIFTING",
    "fault": "OUT OF TOLERANCE",
    "snoozed": "SNOOZED",
}


@dataclass
class ViewModel:
    """Everything the panel draws, assembled by the app each frame."""

    frame: np.ndarray | None = None
    landmarks: Landmarks | None = None
    metrics: PostureMetrics = field(default_factory=PostureMetrics)
    faults: list[Fault] = field(default_factory=list)
    baseline: Baseline | None = None
    aspect: float = 4 / 3
    status: str = "starting"
    message: str = ""
    #: Escalation rung, 0-3. Drives how insistent the panel allows itself to be.
    urgency: int = 0
    #: Seconds the current fault has gone uncorrected, for the "ignored for" readout.
    held_seconds: float = 0.0

    @property
    def primary_fault(self) -> Fault | None:
        """The fault to instruct on — never drift, which has no immediate action."""
        actionable = [f for f in self.faults if f.kind is not FaultKind.DRIFT]
        if actionable:
            return actionable[0]
        return self.faults[0] if self.faults else None

    @property
    def faulty_joints(self) -> frozenset[str]:
        return frozenset(j for fault in self.faults for j in fault.joints)


class PostureOverlay(QWidget):
    """Frameless, always-on-top posture readout."""

    open_requested = Signal()
    snooze_requested = Signal()
    hide_requested = Signal()
    recalibrate_requested = Signal()
    moved = Signal(int, int)

    def __init__(self, thresholds: Thresholds | None = None) -> None:
        super().__init__()
        self.thresholds = thresholds or Thresholds()
        self.model = ViewModel()
        self._drag_origin: QPoint | None = None
        self._pulse = 0.0

        self.setWindowTitle("PostureGuard")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(
            theme.PANEL_WIDTH,
            HEADER_HEIGHT + theme.VIDEO_HEIGHT + FAULT_HEIGHT + READINGS_HEIGHT,
        )
        self.setToolTip("Drag to move · double-click to open · right-click for options")
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        # Drives the attention pulse. Only runs while a fault is actually escalating,
        # so the app is not repainting a border animation all day for nothing.
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(60)
        self._pulse_timer.timeout.connect(self._advance_pulse)

    # --- external API -------------------------------------------------------------

    def show_model(self, model: ViewModel) -> None:
        self.model = model
        if model.urgency >= 2 and not self._pulse_timer.isActive():
            self._pulse_timer.start()
        elif model.urgency < 2 and self._pulse_timer.isActive():
            self._pulse_timer.stop()
            self._pulse = 0.0
        self.update()

    def set_status(self, status: str, message: str = "") -> None:
        self.model.status = status
        self.model.message = message
        self.update()

    def _advance_pulse(self) -> None:
        self._pulse = (self._pulse + 0.08) % 1.0
        self.update()

    # --- interaction ---------------------------------------------------------------

    def _show_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        for text, signal in (
            ("Open PostureGuard", self.open_requested),
            ("Snooze alerts", self.snooze_requested),
            ("Recalibrate", self.recalibrate_requested),
        ):
            action = QAction(text, menu)
            action.triggered.connect(signal)
            menu.addAction(action)
        menu.addSeparator()
        close = QAction("Hide this window", menu)
        close.triggered.connect(self.hide_requested)
        menu.addAction(close)
        menu.exec(self.mapToGlobal(position))

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        self.open_requested.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None:
            self.move(event.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None:
            self._drag_origin = None
            # Report where it landed so the position survives a restart.
            self.moved.emit(self.x(), self.y())

    # --- painting -----------------------------------------------------------------

    @property
    def accent(self) -> QColor:
        return theme.STATE_COLORS.get(self.model.status, theme.MUTED)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        surface = QRectF(0, 0, self.width(), self.height())
        path = QPainterPath()
        path.addRoundedRect(surface, CORNER_RADIUS, CORNER_RADIUS)
        painter.setClipPath(path)
        painter.fillRect(surface, theme.INK)

        y = self._paint_header(painter)
        y = self._paint_view(painter, y)
        y = self._paint_instruction(painter, y)
        self._paint_readings(painter, y)

        # A hairline keeps the panel from dissolving into a dark desktop wallpaper.
        # As escalation climbs the border brightens and breathes — the panel earns
        # peripheral attention gradually rather than shouting from the first frame.
        painter.setClipping(False)
        if self.model.urgency >= 2:
            # Triangle wave, so the pulse eases at both ends instead of snapping.
            swing = 1.0 - abs(self._pulse * 2.0 - 1.0)
            alpha = int(150 + 105 * swing)
            pen = QPen(theme.with_alpha(theme.FAULT, alpha))
            pen.setWidthF(2.0)
        elif self.model.primary_fault is not None:
            pen = QPen(theme.with_alpha(theme.FAULT, 150))
            pen.setWidthF(1.5)
        else:
            pen = QPen(theme.RULE)
            pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        painter.end()

    def _paint_header(self, painter: QPainter) -> float:
        rect = QRectF(0, 0, self.width(), HEADER_HEIGHT)
        painter.fillRect(rect, theme.PANEL)

        painter.setFont(theme.eyebrow_font())
        painter.setPen(theme.MUTED)
        painter.drawText(
            QRectF(theme.GUTTER, 0, 160, HEADER_HEIGHT),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            "Postureguard",
        )

        label = STATUS_LABELS.get(self.model.status, self.model.status.upper())
        painter.setPen(self.accent)
        painter.drawText(
            QRectF(self.width() - 190 - theme.GUTTER, 0, 190, HEADER_HEIGHT),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            label,
        )

        # Status pip, sized to read at a glance from the corner of the eye.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.accent)
        text_width = painter.fontMetrics().horizontalAdvance(label)
        painter.drawEllipse(
            QRectF(self.width() - theme.GUTTER - text_width - 14, HEADER_HEIGHT / 2 - 2.5, 5, 5)
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)

        self._hairline(painter, HEADER_HEIGHT)
        return HEADER_HEIGHT

    def _paint_view(self, painter: QPainter, top: float) -> float:
        rect = QRectF(0, top, self.width(), theme.VIDEO_HEIGHT)
        painter.fillRect(rect, QColor("#0C0E12"))

        model = self.model
        if model.frame is None:
            self._centred_note(painter, rect, "Waiting for camera")
            self._hairline(painter, rect.bottom())
            return rect.bottom()

        transform = render.draw_video(painter, model.frame, rect)

        if model.landmarks is None:
            self._centred_note(painter, rect, model.message or "Step into view")
            self._hairline(painter, rect.bottom())
            return rect.bottom()

        render.draw_plumb_line(painter, model.landmarks, transform)
        if model.baseline is not None:
            render.draw_tolerance_band(
                painter,
                model.landmarks,
                transform,
                model.baseline,
                self.thresholds,
                model.aspect,
                in_tolerance=not model.faults,
            )
        render.draw_skeleton(
            painter, model.landmarks, transform, model.faulty_joints, self.accent
        )

        # Messages belong in the instruction row and nowhere else. Echoing them over
        # the video too made the countdown appear twice and obscured the skeleton the
        # user is being asked to look at.
        self._hairline(painter, rect.bottom())
        return rect.bottom()

    def _paint_instruction(self, painter: QPainter, top: float) -> float:
        rect = QRectF(0, top, self.width(), FAULT_HEIGHT)
        fault = self.model.primary_fault

        if fault is None:
            painter.setFont(theme.cue_font())
            painter.setPen(theme.MUTED)
            painter.drawText(
                rect.adjusted(theme.GUTTER, 0, -theme.GUTTER, 0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                self.model.message or "Posture is within tolerance.",
            )
            self._hairline(painter, rect.bottom())
            return rect.bottom()

        # A tinted ground so a fault is unmistakable in peripheral vision.
        painter.fillRect(rect, theme.with_alpha(theme.FAULT, 26))

        painter.setFont(theme.fault_title_font())
        painter.setPen(theme.BONE)
        painter.drawText(
            QRectF(theme.GUTTER, rect.top() + 5, self.width() - 100, 19),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            fault.title,
        )

        painter.setFont(theme.fault_title_font())
        painter.setPen(theme.FAULT)
        painter.drawText(
            QRectF(self.width() - 80 - theme.GUTTER, rect.top() + 5, 80, 19),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            f"{fault.severity:.1f}×",
        )

        # Only one cue is shown at a time — a list of corrections is a list nobody
        # acts on. But the overlay does mark the other faults' joints red, so the
        # count has to be stated or those markers look arbitrary.
        painter.setFont(theme.reading_label_font())
        painter.setPen(theme.MUTED)
        others = len([f for f in self.model.faults if f.kind is not FaultKind.DRIFT]) - 1
        # Prefer the elapsed time once it is climbing: "held 40s" explains why the
        # border started pulsing, where a fault count does not.
        if self.model.held_seconds >= 5:
            note = f"held {int(self.model.held_seconds)}s"
        elif others > 0:
            note = f"+{others} more"
        else:
            note = ""
        if note:
            painter.drawText(
                QRectF(self.width() - 90 - theme.GUTTER, rect.top() + 22, 90, 10),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                note,
            )

        painter.setFont(theme.cue_font())
        painter.setPen(theme.with_alpha(theme.BONE, 205))
        painter.drawText(
            QRectF(theme.GUTTER, rect.top() + 26, self.width() - 2 * theme.GUTTER - 46, 38),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap),
            fault.cue,
        )

        self._hairline(painter, rect.bottom())
        return rect.bottom()

    def _paint_readings(self, painter: QPainter, top: float) -> None:
        rect = QRectF(0, top, self.width(), READINGS_HEIGHT)
        painter.fillRect(rect, theme.PANEL)

        metrics = self.model.metrics
        columns = [
            ("gap", metrics.head_shoulder_gap, "{:.2f}"),
            ("face", metrics.face_scale, "{:.2f}"),
            ("tilt", metrics.eye_roll, "{:+.0f}°"),
            ("sink", metrics.shoulder_height, "{:.2f}"),
        ]
        column_width = (self.width() - 2 * theme.GUTTER) / len(columns)

        for index, (label, value, fmt) in enumerate(columns):
            x = theme.GUTTER + index * column_width
            painter.setFont(theme.reading_label_font())
            painter.setPen(theme.MUTED)
            painter.drawText(
                QRectF(x, rect.top() + 5, column_width, 10),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                label,
            )
            painter.setFont(theme.reading_font())
            painter.setPen(theme.BONE if value is not None else theme.RULE)
            painter.drawText(
                QRectF(x, rect.top() + 15, column_width, 14),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                fmt.format(value) if value is not None else "—",
            )

    # --- helpers ------------------------------------------------------------------

    def _hairline(self, painter: QPainter, y: float) -> None:
        pen = QPen(theme.RULE)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawLine(QRectF(0, y, self.width(), 0).topLeft(), QRectF(0, y, self.width(), 0).topRight())

    def _centred_note(self, painter: QPainter, rect: QRectF, text: str) -> None:
        painter.setFont(theme.cue_font())
        painter.setPen(theme.with_alpha(theme.BONE, 190))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)
