"""Alert surfaces: the toast, the dimming layer, and the app icon.

Both surfaces are built rather than delegated to the OS. A native notification would be
one less thing to maintain, but it also cannot carry the correction cue in the app's own
voice, cannot offer snooze inline, and on Windows lands in a notification centre where a
posture prompt is worthless ten minutes late.

The dim layer is deliberately click-through. Something that covers the whole screen and
also swallows clicks is a malfunction, however well-intentioned.
"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme

TOAST_WIDTH = 380
TOAST_MARGIN = 28
TOAST_VISIBLE_MS = 7000


def app_icon(size: int = 64) -> QIcon:
    """The app mark, painted rather than shipped as a binary asset.

    A plumb line bisecting a shoulder line — the instrument the whole product is built
    around, reduced to two strokes.
    """
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(theme.INK)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)

    pen = QPen(theme.IN_TOLERANCE)
    pen.setWidthF(size * 0.055)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.drawLine(int(size * 0.5), int(size * 0.18), int(size * 0.5), int(size * 0.82))

    pen.setColor(theme.BONE)
    pen.setWidthF(size * 0.085)
    painter.setPen(pen)
    painter.drawLine(int(size * 0.26), int(size * 0.62), int(size * 0.74), int(size * 0.62))

    pen.setColor(theme.BONE)
    pen.setWidthF(size * 0.075)
    painter.setPen(pen)
    painter.drawLine(int(size * 0.38), int(size * 0.36), int(size * 0.62), int(size * 0.36))
    painter.end()

    return QIcon(pixmap)


class Toast(QWidget):
    """A transient prompt naming the fault and its correction."""

    snoozed = Signal()
    opened = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedWidth(TOAST_WIDTH)

        self._opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(220)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._panel = QWidget()
        self._panel.setObjectName("ToastPanel")
        outer.addWidget(self._panel)

        layout = QVBoxLayout(self._panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(6)

        self._title = QLabel()
        self._title.setObjectName("ToastTitle")
        layout.addWidget(self._title)

        self._cue = QLabel()
        self._cue.setObjectName("ToastCue")
        self._cue.setWordWrap(True)
        layout.addWidget(self._cue)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch(1)

        snooze = QPushButton("Snooze")
        snooze.setObjectName("ToastGhost")
        snooze.setCursor(Qt.CursorShape.PointingHandCursor)
        snooze.clicked.connect(self._on_snooze)
        actions.addWidget(snooze)

        fixed = QPushButton("Fixed it")
        fixed.setObjectName("ToastAction")
        fixed.setCursor(Qt.CursorShape.PointingHandCursor)
        fixed.clicked.connect(self.dismiss)
        actions.addWidget(fixed)
        layout.addLayout(actions)

        self._panel.setStyleSheet(self._panel_style())

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.dismiss)

    def _panel_style(self, tone: QColor | None = None) -> str:
        # The accent states what kind of message this is. A "camera reconnected" notice
        # framed in fault red would read as an alarm about the thing that just resolved.
        accent = (tone or theme.FAULT).name()
        return f"""
        QWidget#ToastPanel {{
            background: {theme.PANEL.name()};
            border: 1px solid {accent};
            border-left: 3px solid {accent};
            border-radius: {theme.RADIUS['md']}px;
        }}
        QLabel#ToastTitle {{
            font-family: "{theme.DISPLAY_FAMILY}";
            font-size: 15px; font-weight: 600;
            color: {theme.BONE.name()};
            background: transparent;
        }}
        QLabel#ToastCue {{
            font-size: 12px;
            color: {theme.MUTED.name()};
            background: transparent;
        }}
        QPushButton#ToastAction {{
            background: {theme.IN_TOLERANCE.name()}; color: {theme.INK.name()};
            border: none; border-radius: 4px; padding: 5px 14px;
            font-size: 12px; font-weight: 600;
        }}
        QPushButton#ToastGhost {{
            background: transparent; color: {theme.MUTED.name()};
            border: none; padding: 5px 10px; font-size: 12px;
        }}
        QPushButton#ToastGhost:hover {{ color: {theme.BONE.name()}; }}
        """

    def _on_snooze(self) -> None:
        self.snoozed.emit()
        self.dismiss()

    def present(self, title: str, cue: str, tone: QColor | None = None) -> None:
        self._panel.setStyleSheet(self._panel_style(tone))
        self._title.setText(title)
        self._cue.setText(cue)
        self.adjustSize()
        self._place()

        self._fade.stop()
        self._opacity.setOpacity(0.0)
        self.show()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.start()
        self._timer.start(TOAST_VISIBLE_MS)

    def _place(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(
            area.right() - self.width() - TOAST_MARGIN,
            area.bottom() - self.height() - TOAST_MARGIN,
        )

    def dismiss(self) -> None:
        self._timer.stop()
        self._fade.stop()
        self._fade.setStartValue(self._opacity.opacity())
        self._fade.setEndValue(0.0)
        # disconnect any prior one-shot handler before attaching a new one, or the
        # window ends up hidden by a stale finish signal from an earlier fade.
        try:
            self._fade.finished.disconnect()
        except RuntimeError:
            pass
        self._fade.finished.connect(self.hide)
        self._fade.start()


class DimOverlay(QWidget):
    """A translucent layer that deepens while a fault is ignored.

    Click-through by design: it is a prompt, not a lock screen.
    """

    def __init__(self, max_opacity: float = 0.40) -> None:
        super().__init__()
        self.max_opacity = max_opacity
        self._progress = 0.0
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

    def set_progress(self, progress: float) -> None:
        """0 hides the layer entirely; 1 is the configured maximum dim."""
        progress = max(0.0, min(progress, 1.0))
        if abs(progress - self._progress) < 0.01 and self.isVisible() == (progress > 0):
            return
        self._progress = progress
        if progress <= 0:
            self.hide()
            return
        self._cover_all_screens()
        if not self.isVisible():
            self.show()
        self.update()

    def _cover_all_screens(self) -> None:
        # A second monitor left undimmed lets the user simply look away from the
        # prompt, which defeats the point of the rung.
        union = QRect()
        for screen in QApplication.screens():
            union = union.united(screen.geometry())
        if union.isValid():
            self.setGeometry(union)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        tint = QColor(theme.INK)
        tint.setAlphaF(self.max_opacity * self._progress)
        painter.fillRect(self.rect(), tint)
        painter.end()
