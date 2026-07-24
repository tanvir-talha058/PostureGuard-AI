"""Painted charts for the History screen.

Deliberate choices, in the order they were made:

**Form before colour.** Daily score is a magnitude per discrete day, so it is columns,
not a line — a line would draw a slope across a Saturday you never sat at the desk and
invent data. The fault breakdown ranks parts of a whole and is a sorted bar chart, not a
pie, because comparing angles is strictly harder than comparing lengths.

**A day with no data is not a day you scored zero.** Untracked days render as a hollow
baseline tick, never as a zero-height bar. Conflating "absent" with "terrible" is the
fastest way to make a history chart lie.

**Colour by job.** The score charts encode magnitude against a threshold, so they use
the reserved status palette. The breakdown chart encodes identity, so it uses the
separate categorical series palette — and every bar is directly labelled, so colour is
never the only thing carrying meaning.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from .. import theme

BAR_RADIUS = 4
BAR_GAP = 2
AXIS_HEIGHT = 22
LABEL_WIDTH = 34


@dataclass(frozen=True)
class Bar:
    """One datum. `value` of None means no data — rendered as absent, not as zero."""

    label: str
    value: float | None
    caption: str = ""
    color: QColor | None = None


def score_color(score: float) -> QColor:
    """Status palette, thresholded. Reserved colours, used for their reserved meaning."""
    if score >= 80:
        return theme.IN_TOLERANCE
    if score >= 60:
        return theme.WARNING
    return theme.FAULT


class _ChartBase(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bars: list[Bar] = []
        self._hot = -1
        self.setMouseTracking(True)

    def set_bars(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.update()

    @property
    def has_data(self) -> bool:
        return any(bar.value is not None for bar in self.bars)

    def _tick_font(self) -> QFont:
        font = QFont(theme.MONO_FAMILY, 7)
        font.setFamilies([theme.MONO_FAMILY, *theme.MONO_FALLBACKS])
        return font

    def _value_font(self) -> QFont:
        font = QFont(theme.MONO_FAMILY, 8)
        font.setFamilies([theme.MONO_FAMILY, *theme.MONO_FALLBACKS])
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def _empty(self, painter: QPainter, message: str) -> None:
        painter.setFont(self._tick_font())
        painter.setPen(theme.FAINT)
        painter.drawText(QRectF(self.rect()), int(Qt.AlignmentFlag.AlignCenter), message)

    def leaveEvent(self, event) -> None:
        self._hot = -1
        self.update()


class ColumnChart(_ChartBase):
    """Vertical columns over an ordered dimension — days, or hours of the day."""

    def __init__(
        self,
        maximum: float = 100.0,
        unit: str = "%",
        empty_message: str = "No data yet",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.maximum = maximum
        self.unit = unit
        self.empty_message = empty_message
        self.setMinimumHeight(170)

    def _plot_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(LABEL_WIDTH, 8, -2, -AXIS_HEIGHT)

    def _bar_rects(self) -> list[tuple[int, QRectF]]:
        plot = self._plot_rect()
        if not self.bars or plot.width() <= 0:
            return []
        slot = plot.width() / len(self.bars)
        rects = []
        for index, bar in enumerate(self.bars):
            left = plot.left() + index * slot
            width = max(slot - BAR_GAP, 1.0)
            if bar.value is None:
                rects.append((index, QRectF(left, plot.bottom() - 2, width, 2)))
                continue
            ratio = max(min(bar.value / self.maximum, 1.0), 0.0)
            height = max(ratio * plot.height(), 2.0)
            rects.append((index, QRectF(left, plot.bottom() - height, width, height)))
        return rects

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.has_data:
            self._empty(painter, self.empty_message)
            painter.end()
            return

        plot = self._plot_rect()
        self._draw_grid(painter, plot)

        painter.setFont(self._tick_font())
        for index, rect in self._bar_rects():
            bar = self.bars[index]
            if bar.value is None:
                # An untracked day: a hollow baseline tick, never a zero-height bar.
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(theme.with_alpha(theme.FAINT, 110))
                painter.drawRect(rect)
            else:
                colour = bar.color or score_color(bar.value)
                if index == self._hot:
                    colour = colour.lighter(118)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(colour)
                # Rounded data-end, square foot: the bar is anchored to the baseline,
                # so rounding the bottom would lift it off its own axis.
                painter.drawRoundedRect(rect, BAR_RADIUS, BAR_RADIUS)
                painter.drawRect(
                    QRectF(rect.left(), rect.bottom() - BAR_RADIUS, rect.width(), BAR_RADIUS)
                )

            painter.setPen(theme.FAINT if bar.value is None else theme.MUTED)
            painter.drawText(
                QRectF(rect.left() - 6, plot.bottom() + 4, rect.width() + 12, AXIS_HEIGHT - 6),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                bar.label,
            )
        painter.end()

    def _draw_grid(self, painter: QPainter, plot: QRectF) -> None:
        """Recessive gridlines at quarters, with the axis labelled once each."""
        pen = QPen(theme.with_alpha(theme.RULE, 150))
        pen.setWidthF(1.0)
        painter.setFont(self._tick_font())
        for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
            y = plot.bottom() - fraction * plot.height()
            painter.setPen(pen)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(theme.FAINT)
            painter.drawText(
                QRectF(0, y - 7, LABEL_WIDTH - 6, 14),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                f"{int(self.maximum * fraction)}{self.unit}",
            )

    def mouseMoveEvent(self, event) -> None:
        position = event.position()
        found = -1
        for index, rect in self._bar_rects():
            column = QRectF(rect.left(), self._plot_rect().top(), rect.width(), self._plot_rect().height())
            if column.contains(position):
                found = index
                break
        if found != self._hot:
            self._hot = found
            self.update()
        if found >= 0:
            bar = self.bars[found]
            text = (
                f"{bar.caption or bar.label}: no data"
                if bar.value is None
                else f"{bar.caption or bar.label}: {bar.value:.0f}{self.unit}"
            )
            QToolTip.showText(event.globalPosition().toPoint(), text, self)


class RankedBarChart(_ChartBase):
    """Horizontal bars, sorted, each directly labelled.

    Direct labels are what let this chart use categorical colour safely — the name and
    the value are always readable, so colour only reinforces identity rather than
    carrying it alone.
    """

    ROW_HEIGHT = 34

    def __init__(self, empty_message: str = "No faults recorded", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.empty_message = empty_message
        self.setMinimumHeight(150)

    def set_bars(self, bars: list[Bar]) -> None:
        super().set_bars(bars)
        self.setMinimumHeight(max(len(bars) * self.ROW_HEIGHT + 8, 100))

    def _row_rects(self) -> list[tuple[int, QRectF, QRectF]]:
        if not self.bars:
            return []
        values = [b.value or 0.0 for b in self.bars]
        peak = max(values) or 1.0
        area = QRectF(self.rect())
        rows = []
        for index, bar in enumerate(self.bars):
            top = area.top() + index * self.ROW_HEIGHT
            row = QRectF(area.left(), top, area.width(), self.ROW_HEIGHT - BAR_GAP)
            track = QRectF(row.left(), row.top() + 17, row.width(), 8)
            filled = QRectF(track)
            filled.setWidth(max(track.width() * ((bar.value or 0.0) / peak), 2.0))
            rows.append((index, row, filled))
        return rows

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if not self.has_data:
            self._empty(painter, self.empty_message)
            painter.end()
            return

        for index, row, filled in self._row_rects():
            bar = self.bars[index]
            colour = bar.color or theme.SERIES[index % len(theme.SERIES)]
            if index == self._hot:
                colour = colour.lighter(118)

            painter.setFont(self._value_font())
            painter.setPen(theme.BONE)
            painter.drawText(
                QRectF(row.left(), row.top(), row.width() - 90, 15),
                int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
                bar.label,
            )
            painter.setPen(theme.MUTED)
            painter.drawText(
                QRectF(row.right() - 90, row.top(), 90, 15),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                bar.caption,
            )

            track = QRectF(filled.left(), filled.top(), row.width(), filled.height())
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(theme.with_alpha(theme.RULE, 130))
            painter.drawRoundedRect(track, 4, 4)
            painter.setBrush(colour)
            painter.drawRoundedRect(filled, 4, 4)
        painter.end()

    def mouseMoveEvent(self, event) -> None:
        position = event.position()
        found = -1
        for index, row, _ in self._row_rects():
            if row.contains(position):
                found = index
                break
        if found != self._hot:
            self._hot = found
            self.update()
        if found >= 0:
            bar = self.bars[found]
            QToolTip.showText(
                event.globalPosition().toPoint(), f"{bar.label} — {bar.caption}", self
            )
