"""Tests for UI code that carries real logic rather than pixels.

Widget rendering is verified by eye through tools/preview_app.py. What is tested here
is the decision-making that happens to live in UI modules — chart data shaping, layout
invariants that have broken before, and the design tokens the charts depend on.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from postureguard import theme  # noqa: E402
from postureguard.ui.charts import Bar, ColumnChart, RankedBarChart, score_color  # noqa: E402
from postureguard.ui.widgets import Card, PageHeader, StatTile, label  # noqa: E402


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


class TestScoreColour:
    def test_uses_the_reserved_status_palette(self):
        assert score_color(95) is theme.IN_TOLERANCE
        assert score_color(70) is theme.WARNING
        assert score_color(30) is theme.FAULT

    def test_thresholds_are_inclusive_at_the_boundary(self):
        assert score_color(80) is theme.IN_TOLERANCE
        assert score_color(60) is theme.WARNING


class TestSeriesPalette:
    def test_series_colours_are_distinct_from_the_status_colours(self):
        """Reusing the fault red as a series would make a breakdown read as an alarm."""
        status = {theme.IN_TOLERANCE.name(), theme.WARNING.name(), theme.FAULT.name()}
        assert not {c.name() for c in theme.SERIES} & status

    def test_there_is_a_colour_for_every_fault_kind(self):
        from postureguard.rules import FaultKind

        assert len(theme.SERIES) >= len(FaultKind)


class TestChartData:
    def test_a_chart_with_only_missing_values_reports_no_data(self, qt_app):
        chart = ColumnChart()
        chart.set_bars([Bar("01", None), Bar("02", None)])
        assert not chart.has_data

    def test_a_single_real_value_counts_as_data(self, qt_app):
        chart = ColumnChart()
        chart.set_bars([Bar("01", None), Bar("02", 42.0)])
        assert chart.has_data

    def test_missing_values_render_as_a_baseline_tick_not_a_zero_bar(self, qt_app):
        """A day you did not work is not a day you scored zero."""
        chart = ColumnChart()
        chart.resize(400, 200)
        chart.set_bars([Bar("01", None), Bar("02", 0.0)])
        rects = dict((i, r) for i, r in chart._bar_rects())
        assert rects[0].height() == pytest.approx(2.0)  # absent: flat tick
        assert rects[1].height() >= 2.0  # a real zero still draws a minimum bar
        assert rects[0].top() > rects[1].top() or rects[1].height() >= rects[0].height()

    def test_zero_and_missing_are_distinguishable(self, qt_app):
        chart = ColumnChart()
        chart.resize(400, 200)
        chart.set_bars([Bar("a", None)])
        absent = chart._bar_rects()[0][1]
        chart.set_bars([Bar("a", 100.0)])
        full = chart._bar_rects()[0][1]
        assert full.height() > absent.height()

    def test_ranked_chart_grows_to_fit_its_rows(self, qt_app):
        chart = RankedBarChart()
        chart.set_bars([Bar(f"f{i}", float(i + 1), f"{i}m") for i in range(5)])
        assert chart.minimumHeight() >= 5 * RankedBarChart.ROW_HEIGHT

    def test_ranked_chart_handles_an_all_zero_series_without_dividing_by_zero(self, qt_app):
        chart = RankedBarChart()
        chart.resize(400, 200)
        chart.set_bars([Bar("a", 0.0, "0m"), Bar("b", 0.0, "0m")])
        assert chart._row_rects()  # must not raise


class TestLayoutInvariants:
    """Regressions for the wrapping bug that clipped every control on Settings."""

    def test_body_labels_wrap_by_default(self, qt_app):
        assert label("some prose", "Body").wordWrap()

    def test_page_subtitles_wrap_by_default(self, qt_app):
        assert label("some prose", "PageSubtitle").wordWrap()

    def test_eyebrows_and_metrics_do_not_wrap(self, qt_app):
        assert not label("GAP", "Eyebrow").wordWrap()
        assert not label("0.62", "Metric").wordWrap()

    def test_a_long_card_subtitle_does_not_widen_the_card(self, qt_app):
        """An unwrapped subtitle used to force its container past the viewport."""
        short = Card("Title", "Short.")
        long = Card("Title", "A subtitle that runs on at considerable length, "
                             "well past any sensible single-line width, and would "
                             "otherwise impose its full extent as a layout minimum.")
        assert long.minimumSizeHint().width() < 600
        assert long.minimumSizeHint().width() < short.minimumSizeHint().width() + 400

    def test_a_long_page_subtitle_does_not_widen_the_header(self, qt_app):
        header = PageHeader("Title", "A subtitle of considerable and unreasonable "
                                     "length that should never dictate layout width.")
        assert header.minimumSizeHint().width() < 600


class TestSettingsRoundTrip:
    """_emit rebuilds Config from the visible controls, so any field without a control
    silently reverts to its default. These pin the ones that have no control."""

    def test_changing_a_setting_preserves_the_mini_window_position(self, qt_app):
        from postureguard.config import Config
        from postureguard.ui.screens.settings import SettingsScreen

        screen = SettingsScreen(Config(mini_x=1200, mini_y=40))
        captured = []
        screen.changed.connect(captured.append)
        screen.sensitivity.slider.setValue(150)

        assert captured, "moving a slider should emit a config change"
        assert (captured[-1].mini_x, captured[-1].mini_y) == (1200, 40)

    def test_changing_a_setting_preserves_unexposed_app_settings(self, qt_app):
        from postureguard.config import Config
        from postureguard.ui.screens.settings import SettingsScreen

        screen = SettingsScreen(Config(start_minimized=True, launch_at_login=True))
        captured = []
        screen.changed.connect(captured.append)
        screen.sensitivity.slider.setValue(120)

        assert captured[-1].start_minimized is True
        assert captured[-1].launch_at_login is True

    def test_building_the_screen_emits_nothing(self, qt_app):
        """Populating controls fires their signals; startup must not look like edits."""
        from postureguard.config import Config
        from postureguard.ui.screens.settings import SettingsScreen

        captured = []
        screen = SettingsScreen(Config())
        screen.changed.connect(captured.append)
        assert captured == []


class TestMiniWindow:
    def test_drift_is_never_the_instruction(self, qt_app):
        """Drift describes ten minutes of history and has no immediate action."""
        from postureguard.overlay import ViewModel
        from postureguard.rules import Fault, FaultKind

        drift = Fault(FaultKind.DRIFT, 2.0, "You have been sinking.", ())
        craning = Fault(FaultKind.FORWARD_HEAD, 1.2, "Chin back.", ())
        model = ViewModel(faults=[drift, craning])
        assert model.primary_fault is craning

    def test_drift_alone_is_still_shown_if_it_is_all_there_is(self, qt_app):
        from postureguard.overlay import ViewModel
        from postureguard.rules import Fault, FaultKind

        drift = Fault(FaultKind.DRIFT, 2.0, "You have been sinking.", ())
        assert ViewModel(faults=[drift]).primary_fault is drift

    def test_the_attention_pulse_only_runs_while_escalating(self, qt_app):
        """A border animation running all day is wasted repainting."""
        from postureguard.overlay import PostureOverlay, ViewModel

        overlay = PostureOverlay()
        overlay.show_model(ViewModel(urgency=0))
        assert not overlay._pulse_timer.isActive()
        overlay.show_model(ViewModel(urgency=2))
        assert overlay._pulse_timer.isActive()
        overlay.show_model(ViewModel(urgency=0))
        assert not overlay._pulse_timer.isActive()

    def test_collapsing_shrinks_to_a_bar(self, qt_app):
        from postureguard.overlay import COLLAPSED_HEIGHT, PostureOverlay

        overlay = PostureOverlay()
        full = overlay.height()
        overlay.set_collapsed(True)
        assert overlay.height() == COLLAPSED_HEIGHT
        assert overlay.height() < full
        overlay.set_collapsed(False)
        assert overlay.height() == full

    def test_collapsing_keeps_the_bottom_edge_anchored(self, qt_app):
        """A corner-parked panel must not grow down off the bottom of the screen."""
        from postureguard.overlay import PostureOverlay

        overlay = PostureOverlay()
        overlay.move(100, 400)
        bottom = overlay.y() + overlay.height()
        overlay.set_collapsed(True)
        assert overlay.y() + overlay.height() == bottom
        overlay.set_collapsed(False)
        assert overlay.y() + overlay.height() == bottom

    def test_collapse_state_is_reported_once_per_change(self, qt_app):
        from postureguard.overlay import PostureOverlay

        overlay = PostureOverlay()
        seen = []
        overlay.collapsed_changed.connect(seen.append)
        overlay.set_collapsed(True)
        overlay.set_collapsed(True)  # no-op, must not re-emit
        overlay.set_collapsed(False)
        assert seen == [True, False]

    def test_it_can_be_constructed_already_collapsed(self, qt_app):
        from postureguard.overlay import COLLAPSED_HEIGHT, PostureOverlay

        assert PostureOverlay(collapsed=True).height() == COLLAPSED_HEIGHT

    def test_every_fault_has_a_short_action_for_the_bar(self, qt_app):
        """The full cue is a sentence; a bar has one line and must not clip it."""
        from postureguard.rules import FAULT_ACTIONS, FaultKind

        for kind in FaultKind:
            assert kind in FAULT_ACTIONS
            action = FAULT_ACTIONS[kind]
            assert action.strip()
            assert len(action) <= 32, f"{kind} action too long for the bar: {action!r}"

    def test_the_short_action_shares_a_verb_with_the_full_cue(self, qt_app):
        """Bar and panel must read as one instruction, not two different ones."""
        from postureguard.rules import FAULT_ACTIONS, _CUES, FaultKind

        for kind in (FaultKind.FORWARD_HEAD, FaultKind.SPINE_FLEXION, FaultKind.LATERAL_TILT):
            verb = FAULT_ACTIONS[kind].split()[0].lower().strip("—")
            assert verb in _CUES[kind].lower()

    def test_faulty_joints_are_collected_from_every_active_fault(self, qt_app):
        from postureguard.overlay import ViewModel
        from postureguard.rules import Fault, FaultKind

        model = ViewModel(
            faults=[
                Fault(FaultKind.FORWARD_HEAD, 1.0, "", ("left_ear",)),
                Fault(FaultKind.LATERAL_TILT, 1.0, "", ("left_eye",)),
            ]
        )
        assert model.faulty_joints == frozenset({"left_ear", "left_eye"})


class TestStatTile:
    def test_recolouring_preserves_the_metric_type_role(self, qt_app):
        """Swapping objectName used to drop the font and leave a tiny number."""
        tile = StatTile("score", "88", "%")
        tile.set_tone("StatusFault")
        assert tile._value.objectName() == "Metric"
        assert theme.FAULT.name() in tile._value.styleSheet()

    def test_notes_are_hidden_until_there_is_one(self, qt_app):
        tile = StatTile("score", "88")
        assert not tile._note.isVisible()
        tile.set_value("88", note="over 3 days")
        assert tile._note.text() == "over 3 days"
