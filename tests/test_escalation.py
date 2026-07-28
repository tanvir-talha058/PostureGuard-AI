import pytest

from postureguard.escalation import Escalator, Level
from postureguard.rules import Fault, FaultKind

CRANING = [Fault(FaultKind.FORWARD_HEAD, 2.0, "Pull your chin back.", ("left_ear",))]
DRIFTING = [Fault(FaultKind.DRIFT, 1.5, "You've been sinking.", ("left_shoulder",))]
CLEAR: list[Fault] = []


def ladder(**kwargs) -> Escalator:
    return Escalator(toast_after_seconds=10, dim_after_seconds=20, dim_ramp_seconds=10, **kwargs)


class TestLadder:
    def test_good_posture_sits_at_none(self):
        assert ladder().update(CLEAR, now=0).level is Level.NONE

    def test_a_fresh_fault_starts_at_the_cue(self):
        assert ladder().update(CRANING, now=0).level is Level.CUE

    def test_ignoring_the_cue_reaches_a_toast(self):
        escalator = ladder()
        escalator.update(CRANING, now=0)
        assert escalator.update(CRANING, now=11).level is Level.TOAST

    def test_continuing_to_ignore_it_reaches_dimming(self):
        escalator = ladder()
        escalator.update(CRANING, now=0)
        assert escalator.update(CRANING, now=21).level is Level.DIM

    def test_the_dim_ramps_in_rather_than_snapping(self):
        escalator = ladder()
        escalator.update(CRANING, now=0)
        assert escalator.update(CRANING, now=21).dim_progress == pytest.approx(0.1, abs=0.01)
        assert escalator.update(CRANING, now=25).dim_progress == pytest.approx(0.5, abs=0.01)
        assert escalator.update(CRANING, now=40).dim_progress == 1.0


class TestReset:
    def test_correcting_posture_drops_straight_back_to_none(self):
        escalator = ladder()
        escalator.update(CRANING, now=0)
        escalator.update(CRANING, now=30)
        assert escalator.update(CLEAR, now=31).level is Level.NONE

    def test_the_clock_restarts_after_a_correction(self):
        """Time counts how long you've ignored the cue, not how long the app has run."""
        escalator = ladder()
        escalator.update(CRANING, now=0)
        escalator.update(CRANING, now=19)
        escalator.update(CLEAR, now=20)
        assert escalator.update(CRANING, now=21).level is Level.CUE


class TestToastDiscipline:
    def test_a_toast_fires_once_per_episode(self):
        escalator = ladder()
        escalator.update(CRANING, now=0)
        fired = [escalator.update(CRANING, now=t).toast_now for t in range(11, 40)]
        assert fired.count(True) == 1

    def test_slipping_twice_in_quick_succession_is_one_toast(self):
        """Fix-then-reslip inside the cooldown is one lapse, not two."""
        escalator = ladder(cooldown_seconds=60)
        escalator.update(CRANING, now=0)
        assert escalator.update(CRANING, now=11).toast_now is True
        escalator.update(CLEAR, now=12)
        escalator.update(CRANING, now=13)
        fired = [escalator.update(CRANING, now=t).toast_now for t in range(14, 40)]
        assert not any(fired)

    def test_a_later_lapse_past_the_cooldown_does_toast_again(self):
        escalator = ladder(cooldown_seconds=30)
        escalator.update(CRANING, now=0)
        assert escalator.update(CRANING, now=11).toast_now is True
        escalator.update(CLEAR, now=12)
        escalator.update(CRANING, now=100)
        assert escalator.update(CRANING, now=111).toast_now is True


class TestHeldTime:
    def test_reports_how_long_the_fault_has_been_held(self):
        escalator = ladder()
        escalator.update(CRANING, now=0)
        assert escalator.update(CRANING, now=14).held_seconds == pytest.approx(14)

    def test_held_time_is_zero_when_posture_is_fine(self):
        assert ladder().update(CLEAR, now=99).held_seconds == 0.0

    def test_held_time_restarts_after_a_correction(self):
        escalator = ladder()
        escalator.update(CRANING, now=0)
        escalator.update(CRANING, now=30)
        escalator.update(CLEAR, now=31)
        assert escalator.update(CRANING, now=32).held_seconds == pytest.approx(0)


class TestQuiet:
    def test_drift_alone_never_escalates_past_the_cue(self):
        """A ten-minute average is not grounds for dimming someone's screen."""
        escalator = ladder()
        escalator.update(DRIFTING, now=0)
        assert escalator.update(DRIFTING, now=500).level is Level.NONE

    def test_suppression_holds_it_at_the_cue(self):
        escalator = ladder()
        escalator.suppress(300, now=0)
        escalator.update(CRANING, now=1)
        assert escalator.update(CRANING, now=100).level is Level.CUE

    def test_escalation_returns_after_suppression_expires(self):
        escalator = ladder()
        escalator.suppress(10, now=0)
        escalator.update(CRANING, now=11)
        assert escalator.update(CRANING, now=40).level is Level.DIM

    def test_disabling_alerts_holds_it_at_the_cue(self):
        escalator = ladder(alerts_enabled=False)
        escalator.update(CRANING, now=0)
        assert escalator.update(CRANING, now=500).level is Level.CUE

    def test_disabling_dim_stops_at_the_toast(self):
        escalator = ladder(dim_enabled=False)
        escalator.update(CRANING, now=0)
        assert escalator.update(CRANING, now=500).level is Level.TOAST

    def test_fullscreen_holds_it_at_the_cue(self):
        """A presentation or a game covering the whole screen is not a moment to
        dim it — but the overlay cue, drawn on the small always-on-top panel, is
        fine to keep showing."""
        escalator = ladder()
        escalator.update(CRANING, now=0)
        held = escalator.update(CRANING, now=500, fullscreen_active=True)
        assert held.level is Level.CUE

    def test_escalation_resumes_once_fullscreen_ends(self):
        """The held-time clock kept running underneath the suppression, so ending
        the fullscreen window picks the ladder back up where it left off rather
        than treating it as a fresh fault."""
        escalator = ladder()
        escalator.update(CRANING, now=0)
        escalator.update(CRANING, now=15, fullscreen_active=True)
        assert escalator.update(CRANING, now=16).level is Level.TOAST
