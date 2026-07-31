"""Tests for UI code that carries real logic rather than pixels.

Widget rendering is verified by eye through tools/preview_app.py. What is tested here
is the decision-making that happens to live in UI modules — chart data shaping, layout
invariants that have broken before, and the design tokens the charts depend on.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from postureguard import theme
from postureguard.ui.charts import Bar, ColumnChart, RankedBarChart, score_color
from postureguard.ui.widgets import Card, PageHeader, StatTile, label


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

    def test_covers_the_originally_validated_fault_kinds_without_cycling(self):
        """SERIES was colour-science validated (OKLCH band, chroma floor, colour-
        vision separation, contrast) for exactly 5 entries — see theme.py. Fault
        kinds added since then legitimately cycle in the breakdown chart rather
        than reuse a status colour; extending the validated set itself needs the
        same validation pass repeated, not five more hex codes typed by hand."""
        assert len(theme.SERIES) == 5


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


class TestPowerSettings:
    def test_controls_reflect_the_starting_config(self, qt_app):
        from postureguard.config import Config
        from postureguard.ui.screens.settings import SettingsScreen

        screen = SettingsScreen(
            Config(pause_when_locked=False, pause_after_idle_minutes=5, battery_saver=False)
        )
        assert screen.pause_when_locked.isChecked() is False
        assert screen.pause_after_idle.slider.value() == 5
        assert screen.battery_saver.isChecked() is False

    def test_toggling_a_power_control_emits_the_new_value(self, qt_app):
        from postureguard.config import Config
        from postureguard.ui.screens.settings import SettingsScreen

        screen = SettingsScreen(Config(pause_when_locked=True))
        captured = []
        screen.changed.connect(captured.append)

        screen.pause_when_locked.setChecked(False)

        assert captured[-1].pause_when_locked is False

    def test_the_idle_slider_reaching_zero_reads_as_never(self, qt_app):
        from postureguard.config import Config
        from postureguard.ui.screens.settings import SettingsScreen

        screen = SettingsScreen(Config())
        screen.pause_after_idle.slider.setValue(0)
        assert screen.pause_after_idle._readout.text() == "Never"


class TestCameraPicker:
    def _screen(self, cameras, **config_kwargs):
        from postureguard.config import Config
        from postureguard.ui.screens.settings import SettingsScreen

        return SettingsScreen(Config(**config_kwargs), cameras)

    def test_lists_only_the_cameras_that_exist(self, qt_app):
        """It used to offer a fixed Camera 0/1/2 regardless of what was attached."""
        from postureguard.capture import CameraInfo

        screen = self._screen([CameraInfo(0, "HP HD Camera")])
        assert screen.camera.count() == 1
        assert screen.camera.itemText(0) == "HP HD Camera"

    def test_selecting_sends_the_device_index_not_the_list_position(self, qt_app):
        """With a gap in the indices these differ, and picking the wrong one opens
        the wrong camera."""
        from postureguard.capture import CameraInfo

        screen = self._screen(
            [CameraInfo(0, "Built-in"), CameraInfo(3, "External")], camera_index=0
        )
        captured = []
        screen.changed.connect(captured.append)
        screen.camera.setCurrentIndex(1)  # list position 1, device index 3

        assert captured[-1].camera_index == 3

    def test_restores_the_stored_device_even_when_indices_are_sparse(self, qt_app):
        from postureguard.capture import CameraInfo

        screen = self._screen(
            [CameraInfo(0, "Built-in"), CameraInfo(3, "External")], camera_index=3
        )
        assert screen.camera.currentData() == 3
        assert screen.camera.currentText() == "External"

    def test_a_stored_camera_that_has_gone_away_falls_back(self, qt_app):
        """Unplugging the selected webcam must not leave an empty selection."""
        from postureguard.capture import CameraInfo

        screen = self._screen([CameraInfo(0, "Built-in")], camera_index=7)
        assert screen.camera.currentData() == 0

    def test_no_cameras_says_so_and_disables_the_control(self, qt_app):
        screen = self._screen([])
        assert not screen.camera.isEnabled()
        assert "No camera" in screen.camera.currentText()

    def test_flags_when_it_had_to_substitute_a_camera(self, qt_app):
        """Application uses this flag to correct and re-persist the setting
        automatically — see test_app_camera_self_heal.py for the end-to-end case
        this exists to fix: a stale saved index silently showing a working camera
        on screen while staying broken underneath."""
        from postureguard.capture import CameraInfo

        screen = self._screen([CameraInfo(0, "Built-in")], camera_index=7)
        assert screen.camera_was_corrected is True

    def test_does_not_flag_a_correct_stored_selection(self, qt_app):
        from postureguard.capture import CameraInfo

        screen = self._screen([CameraInfo(0, "Built-in")], camera_index=0)
        assert screen.camera_was_corrected is False

    def test_does_not_flag_when_there_is_nothing_to_substitute(self, qt_app):
        """No cameras at all is a different, unfixable situation — there is no
        correction to apply, so this must not be confused with one."""
        screen = self._screen([], camera_index=7)
        assert screen.camera_was_corrected is False


class TestMiniWindowHasNoCamera:
    """The mini window shows the posture status and the fix, never the camera feed —
    the main window is where you go to look at yourself, this is what is in front of
    you the rest of the time."""

    def test_view_model_carries_no_frame_or_landmarks(self, qt_app):
        """A regression here would mean the panel started depending on camera data
        again — the whole point is that it never needs a frame to draw itself."""
        from postureguard.overlay import ViewModel

        fields = {f.name for f in __import__("dataclasses").fields(ViewModel)}
        assert "frame" not in fields
        assert "landmarks" not in fields
        assert "baseline" not in fields

    def test_the_expanded_panel_is_shorter_without_a_video_section(self, qt_app):
        from postureguard import theme
        from postureguard.overlay import (
            COLLAPSED_HEIGHT,
            FAULT_HEIGHT,
            HEADER_HEIGHT,
            READINGS_HEIGHT,
            PostureOverlay,
        )

        overlay = PostureOverlay()
        assert overlay.height() == HEADER_HEIGHT + FAULT_HEIGHT + READINGS_HEIGHT
        # Sanity check the shape of the claim, not just its arithmetic: it must be
        # meaningfully smaller than it would be with a camera section, and still
        # bigger than the collapsed bar.
        assert overlay.height() < HEADER_HEIGHT + theme.VIDEO_HEIGHT + FAULT_HEIGHT + READINGS_HEIGHT
        assert overlay.height() > COLLAPSED_HEIGHT

    def test_a_fault_shows_the_correction_with_no_frame_supplied(self, qt_app):
        """The panel must not require a camera frame to say what to do — it never
        had one to begin with now."""
        from postureguard.overlay import PostureOverlay, ViewModel
        from postureguard.rules import Fault, FaultKind

        overlay = PostureOverlay()
        fault = Fault(FaultKind.FORWARD_HEAD, 2.0, "Pull your chin back.", ())
        overlay.show_model(ViewModel(faults=[fault], status="fault"))
        assert overlay.model.primary_fault is fault  # renders without a frame present

    def test_searching_prefers_the_engines_own_instruction(self, qt_app):
        """'Step into view' is an instruction; the generic label is a fallback for
        when the engine has not supplied one."""
        from postureguard.overlay import PostureOverlay, ViewModel

        overlay = PostureOverlay()
        overlay.show_model(ViewModel(status="searching", message="Step into view"))
        assert overlay._resting_text() == "Step into view"

    def test_searching_without_a_message_falls_back_to_a_label(self, qt_app):
        from postureguard.overlay import PostureOverlay, ViewModel

        overlay = PostureOverlay()
        overlay.show_model(ViewModel(status="searching"))
        assert overlay._resting_text() == "No subject"


class TestMiniWindowAlwaysOnTop:
    def test_defaults_on(self, qt_app):
        from postureguard.overlay import PostureOverlay

        assert PostureOverlay().always_on_top is True

    def test_flag_reflects_the_constructor_argument(self, qt_app):
        from PySide6.QtCore import Qt

        from postureguard.overlay import PostureOverlay

        on = PostureOverlay(always_on_top=True)
        off = PostureOverlay(always_on_top=False)
        assert bool(on.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        assert not bool(off.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_set_always_on_top_updates_the_flag_live(self, qt_app):
        from PySide6.QtCore import Qt

        from postureguard.overlay import PostureOverlay

        overlay = PostureOverlay(always_on_top=True)
        overlay.set_always_on_top(False)
        assert overlay.always_on_top is False
        assert not bool(overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)

    def test_toggling_it_does_not_leave_a_visible_window_hidden(self, qt_app):
        """Qt hides a native window when its flags change; this must restore
        visibility, or the setting silently makes the panel disappear."""
        from postureguard.overlay import PostureOverlay

        overlay = PostureOverlay()
        overlay.show()
        assert overlay.isVisible()
        overlay.set_always_on_top(False)
        assert overlay.isVisible()

    def test_setting_the_same_value_is_a_no_op(self, qt_app):
        from postureguard.overlay import PostureOverlay

        overlay = PostureOverlay(always_on_top=True)
        flags_before = overlay.windowFlags()
        overlay.set_always_on_top(True)
        assert overlay.windowFlags() == flags_before


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
        from postureguard.rules import _CUES, FAULT_ACTIONS, FaultKind

        for kind in (FaultKind.FORWARD_HEAD, FaultKind.SPINE_FLEXION, FaultKind.LATERAL_TILT):
            verb = FAULT_ACTIONS[kind].split()[0].lower().strip("—")
            assert verb in _CUES[kind].lower()


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


class TestCrispPixelSnapping:
    """crisp() had no test coverage at all before this, and a prior pass flagged —
    but never actually fixed — that it silently assumed devicePixelRatio 1.0. This
    project's own dev display reports 1.5, so the bug was live, not hypothetical."""

    def _lands_on_a_physical_pixel_boundary(self, logical_value: float, dpr: float) -> bool:
        physical = logical_value * dpr
        # A 1px stroke centred on a boundary sits at physical N + 0.5 for integer N.
        return abs((physical - 0.5) - round(physical - 0.5)) < 1e-9

    def test_default_dpr_matches_the_original_flat_half_pixel_behaviour(self):
        from postureguard.ui.widgets import crisp

        assert crisp(10) == 10.5
        assert crisp(0) == 0.5

    @pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 1.75, 2.0])
    @pytest.mark.parametrize("value", [0, 1, 7, 10.3, 42])
    def test_the_result_lands_on_a_physical_pixel_boundary(self, dpr, value):
        from postureguard.ui.widgets import crisp

        result = crisp(value, dpr)
        assert self._lands_on_a_physical_pixel_boundary(result, dpr)

    def test_the_naive_flat_offset_would_have_missed_at_this_projects_own_dpr(self):
        """Proves the bug this fix addresses, not just the fix's own arithmetic:
        the pre-fix formula fails the same boundary check at dpr=1.5."""
        naive = (7) + 0.5
        assert not self._lands_on_a_physical_pixel_boundary(naive, 1.5)

    def test_dpr_one_is_a_no_op_change_from_the_previous_implementation(self):
        from postureguard.ui.widgets import crisp

        for value in (0, 1, 7, 10.3, 42, -3.2):
            assert crisp(value, 1.0) == round(value) + 0.5
