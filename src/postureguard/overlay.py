"""The always-on-top instrument panel.

A small frameless window the user parks in a screen corner. It is deliberately narrow
and quiet: something that sits in peripheral vision for eight hours cannot afford to be
loud, or it gets closed by lunchtime.

Reading order is fixed and never rearranges — status, view, instruction, readings —
so the eye learns where to look and can check posture in a glance rather than a read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from . import render, theme
from .calibration import Baseline
from .landmarks import Landmarks
from .metrics import PostureMetrics
from .rules import Fault, Thresholds

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

    @property
    def primary_fault(self) -> Fault | None:
        return self.faults[0] if self.faults else None

    @property
    def faulty_joints(self) -> frozenset[str]:
        return frozenset(j for fault in self.faults for j in fault.joints)


class PostureOverlay(QWidget):
    """Frameless, always-on-top posture readout."""

    def __init__(self, thresholds: Thresholds | None = None) -> None:
        super().__init__()
        self.thresholds = thresholds or Thresholds()
        self.model = ViewModel()
        self._drag_origin: QPoint | None = None

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

    # --- external API -------------------------------------------------------------

    def show_model(self, model: ViewModel) -> None:
        self.model = model
        self.update()

    def set_status(self, status: str, message: str = "") -> None:
        self.model.status = status
        self.model.message = message
        self.update()

    # --- dragging -----------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is not None:
            self.move(event.globalPosition().toPoint() - self._drag_origin)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = None

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
        painter.setClipping(False)
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
        others = len(self.model.faults) - 1
        if others > 0:
            painter.setFont(theme.reading_label_font())
            painter.setPen(theme.MUTED)
            painter.drawText(
                QRectF(self.width() - 80 - theme.GUTTER, rect.top() + 22, 80, 10),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"+{others} more",
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
