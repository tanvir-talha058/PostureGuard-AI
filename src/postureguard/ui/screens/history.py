"""History: how posture has actually gone, rather than how it feels like it went."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ... import theme
from ...achievements import compute_achievements
from ...calibration import Baseline
from ...rules import FAULT_TITLES
from ...session import SessionStore
from ..charts import Bar, ColumnChart, RankedBarChart
from ..widgets import Card, EmptyState, PageHeader, StatTile, button, label, plain

S = theme.SPACE

RANGES = ((7, "7 days"), (14, "14 days"), (30, "30 days"))


def _duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    minutes, _ = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _hour_label(hour: int) -> str:
    """Sparse hour ticks — 24 labels in a row is noise, six is a scale."""
    return f"{hour:02d}" if hour % 4 == 0 else ""


class HistoryScreen(QWidget):
    def __init__(self, store: SessionStore, baseline_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._baseline_path = baseline_path
        self.days = 14

        layout = QVBoxLayout(self)
        layout.setContentsMargins(S["xl"], S["xl"], S["xl"], S["xl"])
        layout.setSpacing(S["lg"])

        header = PageHeader("History", "Where your posture holds up, and where it gives way.")
        self._range_buttons: dict[int, object] = {}
        for days, text in RANGES:
            control = button(text, "Ghost")
            control.clicked.connect(lambda _=False, d=days: self.set_range(d))
            header.add_action(control)
            self._range_buttons[days] = control
        layout.addWidget(header)

        summary = QHBoxLayout()
        summary.setSpacing(S["lg"])
        self.average_tile = StatTile("average score", "—", "%")
        self.best_tile = StatTile("best day", "—")
        self.tracked_tile = StatTile("time tracked", "—")
        self.worst_hour_tile = StatTile("weakest hour", "—")
        for tile in (self.average_tile, self.best_tile, self.tracked_tile, self.worst_hour_tile):
            card = Card()
            card.add(tile)
            summary.addWidget(card, 1)
        layout.addLayout(summary)

        charts = QGridLayout()
        charts.setSpacing(S["lg"])
        layout.addLayout(charts, 1)

        self.daily_card = Card(
            "Daily posture score",
            "Share of tracked time spent within tolerance. Untracked days are left blank.",
        )
        self.daily_chart = ColumnChart(empty_message="Nothing tracked yet")
        self.daily_card.add(self.daily_chart, 1)
        charts.addWidget(self.daily_card, 0, 0, 1, 2)

        self.breakdown_card = Card(
            "Where the time goes", "Time spent in each fault, worst first."
        )
        self.breakdown_chart = RankedBarChart()
        self.breakdown_card.add(self.breakdown_chart)
        self.breakdown_card.add_stretch()
        charts.addWidget(self.breakdown_card, 1, 0)

        self.hourly_card = Card(
            "By hour of day", "When posture reliably falls apart."
        )
        self.hourly_chart = ColumnChart(empty_message="Nothing tracked yet")
        self.hourly_card.add(self.hourly_chart, 1)
        charts.addWidget(self.hourly_card, 1, 1)

        self.milestones_card = Card("Milestones", "A fixed set of things worth noticing.")
        self._milestones_list = QVBoxLayout()
        self._milestones_list.setSpacing(S["sm"])
        self.milestones_card.add(plain(self._milestones_list))
        charts.addWidget(self.milestones_card, 2, 0, 1, 2)

        self.empty = EmptyState(
            "No history yet",
            "Once you have spent a little time on the Live screen, your daily scores, "
            "fault breakdown and hour-by-hour profile appear here.",
        )
        layout.addWidget(self.empty)

        self.set_range(14)

    def set_range(self, days: int) -> None:
        self.days = days
        for value, control in self._range_buttons.items():
            control.setStyleSheet(
                f"color: {theme.BONE.name()};" if value == days else ""
            )
        self.refresh()

    # --- data ---------------------------------------------------------------------

    def refresh(self) -> None:
        self._fill_milestones()

        summaries = self.store.daily_summaries(days=self.days)
        tracked_total = sum(s.tracked_seconds for s in summaries)

        has_data = tracked_total > 0
        self.empty.setVisible(not has_data)
        for card in (self.daily_card, self.breakdown_card, self.hourly_card):
            card.setVisible(has_data)
        if not has_data:
            for tile in (self.average_tile, self.best_tile, self.tracked_tile, self.worst_hour_tile):
                tile.set_value("—")
            return

        self._fill_daily(summaries)
        self._fill_breakdown()
        self._fill_hourly()
        self._fill_summary(summaries, tracked_total)

    def _fill_milestones(self) -> None:
        while self._milestones_list.count():
            item = self._milestones_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        baseline = Baseline.load(self._baseline_path)
        for achievement in compute_achievements(self.store, baseline):
            text = f"{'Earned' if achievement.earned else 'Not yet'} — {achievement.title}"
            row = label(text, "Body")
            # Elided, not wrapped — same reasoning as StatTile.set_value's note: a
            # wrapped label reports its full single-line width as a layout minimum
            # and silently grows the card taller than intended.
            row.setWordWrap(False)
            metrics = row.fontMetrics()
            width = max(row.width(), 80)
            row.setText(metrics.elidedText(text, Qt.TextElideMode.ElideRight, width))
            row.setToolTip(f"{text}\n{achievement.description}")
            row.setStyleSheet(
                f"color: {theme.IN_TOLERANCE.name()};" if achievement.earned
                else f"color: {theme.MUTED.name()};"
            )
            self._milestones_list.addWidget(row)
        self._milestones_list.addStretch(1)

    def _fill_daily(self, summaries) -> None:
        self.daily_chart.set_bars(
            [
                Bar(
                    label=s.day.strftime("%d"),
                    # Untracked days pass None, not 0 — a day off is not a bad day.
                    value=s.score if s.tracked_seconds > 0 else None,
                    caption=s.day.strftime("%a %d %b"),
                )
                for s in summaries
            ]
        )

    def _fill_breakdown(self) -> None:
        breakdown = self.store.fault_breakdown(days=self.days)
        self.breakdown_chart.set_bars(
            [
                Bar(
                    label=FAULT_TITLES.get(kind, kind.value),
                    value=float(seconds),
                    caption=_duration(seconds),
                    color=theme.SERIES[index % len(theme.SERIES)],
                )
                for index, (kind, seconds) in enumerate(breakdown.items())
            ]
        )

    def _fill_hourly(self) -> None:
        profile = self.store.hourly_profile(days=self.days)
        self.hourly_chart.set_bars(
            [
                Bar(
                    label=_hour_label(hour.hour),
                    value=hour.score if hour.tracked_seconds > 0 else None,
                    caption=f"{hour.hour:02d}:00",
                )
                for hour in profile
            ]
        )

    def _fill_summary(self, summaries, tracked_total: int) -> None:
        tracked_days = [s for s in summaries if s.tracked_seconds > 0]
        # Weight by time, not by day: ten minutes on Sunday should not count as much
        # as a full Tuesday when reporting an average.
        good = sum(s.in_tolerance_seconds for s in tracked_days)
        average = 100.0 * good / tracked_total if tracked_total else 0.0
        self.average_tile.set_value(f"{average:.0f}")
        self.average_tile.set_tone(
            "StatusGood" if average >= 80 else "StatusWarn" if average >= 60 else "StatusFault"
        )

        best = max(tracked_days, key=lambda s: s.score, default=None)
        self.best_tile.set_value(
            f"{best.score:.0f}%" if best else "—",
            note=best.day.strftime("%a %d %b") if best else "",
        )

        self.tracked_tile.set_value(_duration(tracked_total), note=f"over {len(tracked_days)} days")

        profile = [h for h in self.store.hourly_profile(days=self.days) if h.tracked_seconds > 60]
        worst = min(profile, key=lambda h: h.score, default=None)
        self.worst_hour_tile.set_value(
            f"{worst.hour:02d}:00" if worst else "—",
            note=f"{worst.score:.0f}% in tolerance" if worst else "",
        )
