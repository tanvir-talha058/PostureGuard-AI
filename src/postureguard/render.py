"""Painting the camera view, the skeleton, and the correction guides.

The guides are the point of this module. A skeleton alone tells the user they are being
watched; it does not tell them what to do. Two devices carry the instruction:

**The plumb line** — a vertical dropped through the shoulder midpoint, the oldest
posture-assessment instrument there is. It gives the eye a reference for "upright".

**The tolerance band** — a horizontal band at the height the ears *should* occupy,
computed from the user's own calibration and the same threshold the rule engine uses.
Ears inside the band means in tolerance; ears below it means craning. It shows where to
move to, which is the difference between an alarm and a correction.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen

from . import theme
from .calibration import Baseline
from .landmarks import Landmarks
from .rules import Thresholds

#: Bones worth drawing from the nine joints we track. Deliberately sparse — this is a
#: posture reference, not an anatomy chart.
SKELETON_EDGES: tuple[tuple[str, str], ...] = (
    ("left_shoulder", "right_shoulder"),
    ("left_shoulder", "left_hip"),
    ("right_shoulder", "right_hip"),
    ("left_hip", "right_hip"),
    ("left_ear", "right_ear"),
    ("left_eye", "right_eye"),
)

JOINT_SIZE = 5.0


@dataclass(frozen=True)
class FrameTransform:
    """Maps normalized landmark coordinates into the on-screen video rect.

    The frame is scaled to *cover* the rect and centre-cropped, so landmarks have to
    travel through the same transform as the pixels or the skeleton drifts off the body.
    """

    rect: QRectF
    scale: float
    offset_x: float
    offset_y: float
    frame_width: int
    frame_height: int

    def to_screen(self, x: float, y: float) -> QPointF:
        return QPointF(
            self.rect.x() + x * self.frame_width * self.scale + self.offset_x,
            self.rect.y() + y * self.frame_height * self.scale + self.offset_y,
        )

    def length(self, normalized_x_span: float) -> float:
        """Convert a normalized horizontal span into pixels."""
        return normalized_x_span * self.frame_width * self.scale


def compute_transform(frame: np.ndarray, rect: QRectF) -> FrameTransform:
    height, width = frame.shape[:2]
    scale = max(rect.width() / width, rect.height() / height)
    return FrameTransform(
        rect=rect,
        scale=scale,
        offset_x=(rect.width() - width * scale) / 2,
        offset_y=(rect.height() - height * scale) / 2,
        frame_width=width,
        frame_height=height,
    )


def to_qimage(frame: np.ndarray) -> QImage:
    """BGR numpy array to QImage, without holding a reference to freed memory."""
    height, width = frame.shape[:2]
    # rgbSwapped handles BGR; copy() detaches from the numpy buffer, which Qt would
    # otherwise keep pointing at after the array is garbage collected.
    return QImage(
        frame.data, width, height, 3 * width, QImage.Format.Format_RGB888
    ).rgbSwapped().copy()


def draw_video(painter: QPainter, frame: np.ndarray, rect: QRectF) -> FrameTransform:
    transform = compute_transform(frame, rect)
    painter.save()
    painter.setClipRect(rect)
    image = to_qimage(frame)
    painter.drawImage(
        QRectF(
            rect.x() + transform.offset_x,
            rect.y() + transform.offset_y,
            transform.frame_width * transform.scale,
            transform.frame_height * transform.scale,
        ),
        image,
    )
    # Knock the camera image back so the overlaid guides stay legible over any scene.
    painter.fillRect(rect, theme.with_alpha(theme.INK, 118))
    painter.restore()
    return transform


def _midpoint(landmarks: Landmarks, a: str, b: str) -> tuple[float, float] | None:
    pa, pb = landmarks.get(a), landmarks.get(b)
    if pa is None and pb is None:
        return None
    if pa is None:
        return (pb.x, pb.y)
    if pb is None:
        return (pa.x, pa.y)
    return ((pa.x + pb.x) / 2, (pa.y + pb.y) / 2)


def draw_skeleton(
    painter: QPainter,
    landmarks: Landmarks,
    transform: FrameTransform,
    faulty_joints: frozenset[str],
    accent: QColor,
) -> None:
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    for a, b in SKELETON_EDGES:
        pa, pb = landmarks.get(a), landmarks.get(b)
        if pa is None or pb is None:
            continue
        implicated = a in faulty_joints or b in faulty_joints
        pen = QPen(theme.with_alpha(theme.FAULT if implicated else theme.BONE, 210))
        pen.setWidthF(2.0 if implicated else 1.4)
        painter.setPen(pen)
        painter.drawLine(
            transform.to_screen(pa.x, pa.y), transform.to_screen(pb.x, pb.y)
        )

    # The neck: ear midpoint to shoulder midpoint. This is the segment forward-head
    # posture actually collapses, so it earns its own stroke.
    ears = _midpoint(landmarks, "left_ear", "right_ear")
    shoulders = _midpoint(landmarks, "left_shoulder", "right_shoulder")
    if ears and shoulders:
        implicated = bool(faulty_joints & {"left_ear", "right_ear"})
        pen = QPen(theme.with_alpha(theme.FAULT if implicated else theme.BONE, 210))
        pen.setWidthF(2.0 if implicated else 1.4)
        painter.setPen(pen)
        painter.drawLine(
            transform.to_screen(*ears), transform.to_screen(*shoulders)
        )

    # Square reticles rather than dots — this is a measuring instrument.
    for name, point in landmarks.points.items():
        if landmarks.get(name) is None:
            continue
        centre = transform.to_screen(point.x, point.y)
        faulty = name in faulty_joints
        size = JOINT_SIZE + (2.0 if faulty else 0.0)
        box = QRectF(
            centre.x() - size / 2, centre.y() - size / 2, size, size
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillRect(box, theme.FAULT if faulty else accent)
        if faulty:
            pen = QPen(theme.with_alpha(theme.FAULT, 120))
            pen.setWidthF(1.0)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(centre, size * 1.5, size * 1.5)

    painter.restore()


def draw_plumb_line(
    painter: QPainter, landmarks: Landmarks, transform: FrameTransform
) -> None:
    """A vertical reference through the shoulder midpoint."""
    shoulders = _midpoint(landmarks, "left_shoulder", "right_shoulder")
    if shoulders is None:
        return
    x = transform.to_screen(*shoulders).x()
    pen = QPen(theme.with_alpha(theme.IN_TOLERANCE, 90))
    pen.setWidthF(1.0)
    pen.setStyle(Qt.PenStyle.DashLine)
    pen.setDashPattern([2, 5])
    painter.save()
    painter.setPen(pen)
    painter.drawLine(
        QPointF(x, transform.rect.top()), QPointF(x, transform.rect.bottom())
    )
    painter.restore()


def draw_tolerance_band(
    painter: QPainter,
    landmarks: Landmarks,
    transform: FrameTransform,
    baseline: Baseline,
    thresholds: Thresholds,
    aspect: float,
    in_tolerance: bool,
) -> None:
    """The band the ears should sit in, from this user's own calibration.

    Derived from exactly the numbers the rule engine checks, so what the user sees and
    what triggers an alert can never disagree.
    """
    baseline_gap = baseline.get("head_shoulder_gap")
    left, right = landmarks.get("left_shoulder"), landmarks.get("right_shoulder")
    if baseline_gap is None or left is None or right is None:
        return

    # Shoulder width in pixels, measured in the aspect-corrected space the gap ratio
    # was defined in.
    dx = (left.x - right.x) * aspect
    dy = left.y - right.y
    width_px = transform.length((dx**2 + dy**2) ** 0.5 / aspect)
    if width_px <= 1:
        return

    shoulders = _midpoint(landmarks, "left_shoulder", "right_shoulder")
    if shoulders is None:
        return
    shoulder_y = transform.to_screen(*shoulders).y()

    # y grows downward, so a larger gap sits higher on screen.
    ideal_y = shoulder_y - baseline_gap * width_px
    floor_y = shoulder_y - baseline_gap * (1 - thresholds.forward_head_gap_drop) * width_px

    colour = theme.IN_TOLERANCE if in_tolerance else theme.FAULT
    band = QRectF(
        transform.rect.left(),
        ideal_y - 6,
        transform.rect.width(),
        max(floor_y - ideal_y + 6, 4),
    )

    painter.save()
    painter.setClipRect(transform.rect)
    painter.fillRect(band, theme.with_alpha(colour, 34))

    pen = QPen(theme.with_alpha(colour, 150))
    pen.setWidthF(1.0)
    painter.setPen(pen)
    painter.drawLine(
        QPointF(band.left(), band.top()), QPointF(band.right(), band.top())
    )
    pen.setStyle(Qt.PenStyle.DotLine)
    painter.setPen(pen)
    painter.drawLine(
        QPointF(band.left(), band.bottom()), QPointF(band.right(), band.bottom())
    )

    label_font = theme.reading_label_font()
    painter.setFont(label_font)
    painter.setPen(theme.with_alpha(colour, 200))
    painter.drawText(
        QRectF(band.left() + 6, band.top() - 12, 120, 12),
        int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
        "EAR TOLERANCE",
    )
    painter.restore()
