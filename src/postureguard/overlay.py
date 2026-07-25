"""The always-on-top mini window.

A small frameless panel the user parks in a screen corner. This is the surface that
actually changes posture: the main window is where you go to look at your posture, but
this is what is in front of you at the moment you are getting it wrong.

Deliberately narrow and quiet. Something that sits in peripheral vision for eight hours
cannot afford to be loud, or it gets closed by lunchtime — so it stays calm while you
are fine, and earns attention only as a fault is ignored.

No camera feed here, by design — not just for the collapsed bar but in this window's
only other state. The camera view and skeleton belong to the main window, where you go
to look at your posture; this window exists for the moment you are *not* looking at it,
and a live self-view sitting in peripheral vision all day is a webcam-on-desktop
experience nobody wants regardless of what it's showing. What this window says instead
is the two things that fit that moment: what is wrong, and what to do about it.

Reading order is fixed and never rearranges — status, instruction, readings — so the
eye learns where to look and can check posture in a glance rather than a read.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QWidget

from . import theme
from .metrics import PostureMetrics
from .rules import Fault, FaultKind

HEADER_HEIGHT = 30
FAULT_HEIGHT = 68
READINGS_HEIGHT = 34
CORNER_RADIUS = 10

#: Collapsed, the panel is a single bar carrying the instruction and nothing else.
#: No camera, no skeleton, no readings — at this size they would be decoration, and
#: what the user needs mid-task is the correction, not the evidence for it.
COLLAPSED_HEIGHT = 46
ACCENT_BAR_WIDTH = 3

STATUS_LABELS = {
    "starting": "STARTING",
    "calibrating": "CALIBRATING",
    "searching": "NO SUBJECT",
    "camera_lost": "CAMERA LOST",
    "paused": "PAUSED",
    "in_tolerance": "IN TOLERANCE",
    "drifting": "DRIFTING",
    "fault": "OUT OF TOLERANCE",
    "snoozed": "SNOOZED",
}


@dataclass
class ViewModel:
    """Everything the panel draws, assembled by the app each frame.

    No frame, landmarks or baseline: this panel never shows the camera, so it never
    needs them. The main window's own view (ui/screens/live.py) carries those.
    """

    metrics: PostureMetrics = field(default_factory=PostureMetrics)
    faults: list[Fault] = field(default_factory=list)
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


class PostureOverlay(QWidget):
    """Frameless, always-on-top posture readout."""

    open_requested = Signal()
    snooze_requested = Signal()
    hide_requested = Signal()
    recalibrate_requested = Signal()
    moved = Signal(int, int)
    collapsed_changed = Signal(bool)

    def __init__(self, collapsed: bool = False, always_on_top: bool = True) -> None:
        super().__init__()
        self.model = ViewModel()
        self._drag_origin: QPoint | None = None
        self._pulse = 0.0
        self._collapsed = collapsed
        self._always_on_top = always_on_top

        self.setWindowTitle("PostureGuard")
        self._apply_window_flags()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._apply_size()
        self.setToolTip(
            "Drag to move · double-click to collapse or expand · right-click for options"
        )
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)

        # Drives the attention pulse. Only runs while a fault is actually escalating,
        # so the app is not repainting a border animation all day for nothing.
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(60)
        self._pulse_timer.timeout.connect(self._advance_pulse)

    # --- collapse -------------------------------------------------------------------

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    def _apply_size(self) -> None:
        full = HEADER_HEIGHT + FAULT_HEIGHT + READINGS_HEIGHT
        self.setFixedSize(
            theme.PANEL_WIDTH, COLLAPSED_HEIGHT if self._collapsed else full
        )

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self._collapsed:
            return
        # Collapse toward the bottom edge. Growing downward off the bottom of the
        # screen is how a corner-parked panel ends up half out of view.
        bottom = self.y() + self.height()
        self._collapsed = collapsed
        self._apply_size()
        self.move(self.x(), bottom - self.height())
        self.collapsed_changed.emit(collapsed)
        self.moved.emit(self.x(), self.y())
        self.update()

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)

    # --- always on top --------------------------------------------------------------
    #
    # A posture tool only works if the correction is in front of you at the moment
    # you need it — a mini window that some other maximized app can bury is a mini
    # window that stops correcting anything within about ten minutes of use. On by
    # default for exactly that reason; still a real setting, not hardcoded, because a
    # user running a full-screen presentation or a game legitimately wants it out of
    # the way sometimes without having to hide the window entirely.

    @property
    def always_on_top(self) -> bool:
        return self._always_on_top

    def _apply_window_flags(self) -> None:
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
        if self._always_on_top:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def set_always_on_top(self, always_on_top: bool) -> None:
        if always_on_top == self._always_on_top:
            return
        self._always_on_top = always_on_top
        # Changing window flags on an already-created native window implicitly hides
        # it (Qt has to recreate the underlying platform window) — reapply visibility
        # afterward, or the panel silently vanishes the moment the setting is toggled.
        was_visible = self.isVisible()
        self._apply_window_flags()
        if was_visible:
            self.show()

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

        expand = QAction("Expand" if self._collapsed else "Collapse to a bar", menu)
        expand.triggered.connect(self.toggle_collapsed)
        menu.addAction(expand)
        menu.addSeparator()

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
        # Shade the panel, the way double-clicking a title bar has always done.
        # Opening the main window stays on the context menu, where an action that
        # takes over the screen belongs.
        self.toggle_collapsed()

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

        if self._collapsed:
            self._paint_bar(painter, surface)
        else:
            y = self._paint_header(painter)
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

    def _paint_bar(self, painter: QPainter, surface: QRectF) -> None:
        """Collapsed: the instruction, and nothing that is not the instruction."""
        fault = self.model.primary_fault
        colour = self.accent
        painter.fillRect(surface, theme.PANEL)

        if fault is not None:
            # Tint the whole bar so a fault is unmistakable in peripheral vision,
            # where a small coloured strip alone would not register.
            painter.fillRect(surface, theme.with_alpha(colour, 30))

        # A coloured edge carries the state even when the text is not being read.
        painter.fillRect(QRectF(0, 0, ACCENT_BAR_WIDTH, surface.height()), colour)

        left = ACCENT_BAR_WIDTH + theme.GUTTER
        held = self.model.held_seconds
        note = f"{int(held)}s" if fault is not None and held >= 5 else ""
        note_width = 44 if note else 0

        painter.setFont(theme.reading_label_font())
        painter.setPen(theme.MUTED)
        if note:
            painter.drawText(
                QRectF(surface.width() - note_width - theme.GUTTER, 0, note_width, surface.height()),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                note,
            )

        text_rect = QRectF(
            left, 0, surface.width() - left - note_width - theme.GUTTER * 1.5, surface.height()
        )
        painter.setFont(theme.fault_title_font())

        if fault is not None:
            painter.setPen(theme.BONE)
            text = fault.action
        else:
            painter.setPen(theme.MUTED)
            text = self._resting_text()

        # Elide rather than wrap or overflow: the bar has one line, and a clipped
        # instruction is worse than a shortened one.
        metrics = painter.fontMetrics()
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(text_rect.width())),
        )

    def _resting_text(self) -> str:
        """What the bar says when there is nothing to correct."""
        status = self.model.status
        if status == "calibrating":
            return self.model.message or "Calibrating…"
        if status == "camera_lost":
            return "Camera disconnected"
        if status == "paused":
            return self.model.message or "Paused — no activity"
        if status == "searching":
            # The engine already sends "Step into view" here — an instruction, not
            # just a label — which is exactly the register this panel wants.
            return self.model.message or "No subject"
        if status == "snoozed":
            return "Alerts snoozed"
        if status == "starting":
            return "Starting…"
        return "Posture is fine"

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

    def _paint_instruction(self, painter: QPainter, top: float) -> float:
        rect = QRectF(0, top, self.width(), FAULT_HEIGHT)
        fault = self.model.primary_fault

        if fault is None:
            # Everything that used to be a message painted over the video — waiting
            # for the camera, stepping into view, paused, disconnected — now has
            # nowhere to live but here, so it goes through the same status-to-text
            # mapping the collapsed bar already uses. One source of truth for what
            # each resting state says, rather than two copies drifting apart.
            painter.setFont(theme.cue_font())
            painter.setPen(theme.MUTED)
            painter.drawText(
                rect.adjusted(theme.GUTTER, 0, -theme.GUTTER, 0),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextWordWrap),
                self._resting_text(),
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
        from .ui.widgets import crisp

        pen = QPen(theme.RULE)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        # Rounds in physical-pixel space (via devicePixelRatioF), or the offset that
        # keeps this crisp at 100% scaling drifts back off the pixel grid at 125%/150%.
        edge = crisp(y, self.devicePixelRatioF())
        painter.drawLine(QPointF(0, edge), QPointF(self.width(), edge))
