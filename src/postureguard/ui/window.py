"""The application window: navigation rail plus a stack of screens."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import theme
from .controller import LiveState
from .widgets import label

S = theme.SPACE

#: Order matters — this is the order the rail presents, running from what the user
#: checks constantly to what they set once.
SCREENS = (
    ("live", "Live"),
    ("history", "History"),
    ("exercises", "Exercises"),
    ("settings", "Settings"),
)


class StatusPip(QWidget):
    """The rail's footer state light — readable without reading."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._colour = theme.MUTED

    def set_state(self, status: str) -> None:
        self._colour = theme.STATE_COLORS.get(status, theme.MUTED)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(theme.with_alpha(self._colour, 60))
        painter.drawEllipse(self.rect())
        painter.setBrush(self._colour)
        painter.drawEllipse(self.rect().adjusted(3, 3, -3, -3))
        painter.end()


class Sidebar(QFrame):
    navigated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(theme.SIDEBAR_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, S["xl"], 0, S["lg"])
        layout.setSpacing(0)

        mark = QVBoxLayout()
        mark.setContentsMargins(S["lg"], 0, S["lg"], S["xl"])
        mark.setSpacing(1)
        mark.addWidget(label("POSTUREGUARD", "WordMark"))
        mark.addWidget(label("POSTURE INSTRUMENT", "WordMarkSub"))
        layout.addLayout(mark)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for key, text in SCREENS:
            button = QPushButton(text)
            button.setObjectName("NavItem")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _=False, k=key: self.navigated.emit(k))
            self._group.addButton(button)
            self._buttons[key] = button
            layout.addWidget(button)

        layout.addStretch(1)

        footer = QHBoxLayout()
        footer.setContentsMargins(S["lg"], 0, S["lg"], 0)
        footer.setSpacing(S["sm"])
        self.pip = StatusPip()
        footer.addWidget(self.pip)
        self.status_text = label("Starting", "Body")
        footer.addWidget(self.status_text)
        footer.addStretch(1)
        layout.addLayout(footer)

        privacy = label("Runs entirely on this device", "Eyebrow")
        privacy.setContentsMargins(S["lg"], S["md"], S["lg"], 0)
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

    def select(self, key: str) -> None:
        if key in self._buttons:
            self._buttons[key].setChecked(True)


class MainWindow(QWidget):
    """Shell. Screens are injected so this file never grows a dependency on any one."""

    closing = Signal()
    #: Fired whenever the window becomes visible or hidden, including the hide that
    #: follows an accepted close event (closing this window minimizes to tray rather
    #: than quitting, so "closed" and "hidden" are the same event here). The controller
    #: uses this to decide whether the full frame rate is actually being watched.
    shown = Signal()
    hidden = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PostureGuard")
        self.resize(QSize(*theme.WINDOW_SIZE))
        self.setMinimumSize(940, 640)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar()
        self.sidebar.navigated.connect(self.show_screen)
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self._screens: dict[str, QWidget] = {}

    def add_screen(self, key: str, widget: QWidget) -> QWidget:
        self._screens[key] = widget
        self.stack.addWidget(widget)
        return widget

    def show_screen(self, key: str) -> None:
        widget = self._screens.get(key)
        if widget is None:
            return
        self.stack.setCurrentWidget(widget)
        self.sidebar.select(key)
        # Screens that aggregate stored data are stale the moment you leave them;
        # refreshing on entry costs nothing and avoids a manual reload button.
        refresh = getattr(widget, "refresh", None)
        if callable(refresh):
            refresh()

    def on_state(self, state: LiveState) -> None:
        status = state.reading.status
        self.sidebar.pip.set_state(status)
        self.sidebar.status_text.setText(self._status_text(state))

    def _status_text(self, state: LiveState) -> str:
        if state.paused:
            return "Paused"
        if not state.camera_healthy:
            return "Camera lost"
        if state.calibrating:
            return "Calibrating"
        fault = state.intervention.fault
        if state.reading.status == "snoozed":
            return "Snoozed"
        if state.reading.status == "searching":
            return "No subject"
        if fault is not None:
            return fault.title
        if state.reading.status == "drifting":
            return "Drifting"
        return "In tolerance"

    def closeEvent(self, event: QCloseEvent) -> None:
        self.closing.emit()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.shown.emit()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.hidden.emit()
