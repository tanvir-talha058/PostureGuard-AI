import pytest

from postureguard.rules import FaultKind
from postureguard.stretches import (
    ALL_EXERCISES,
    STAND_AND_WALK,
    BreakTimer,
    exercises_for,
    routine_for,
)


class TestLibrary:
    def test_every_exercise_has_usable_instructions(self):
        for exercise in ALL_EXERCISES:
            assert exercise.name.strip()
            assert exercise.purpose.strip()
            assert len(exercise.steps) >= 3
            assert exercise.seconds > 0

    @pytest.mark.parametrize(
        "fault",
        [
            FaultKind.FORWARD_HEAD,
            FaultKind.SPINE_FLEXION,
            FaultKind.LATERAL_TILT,
            FaultKind.SCREEN_TOO_CLOSE,
        ],
    )
    def test_every_detectable_fault_has_a_routine(self, fault):
        """A fault the app reports but cannot advise on is a dead end for the user."""
        assert exercises_for(fault)


class TestRoutines:
    def test_a_routine_targets_the_dominant_fault(self):
        routine = routine_for(FaultKind.FORWARD_HEAD)
        assert any(e.targets is FaultKind.FORWARD_HEAD for e in routine.exercises)

    def test_a_routine_explains_why_these_exercises(self):
        assert "forward" in routine_for(FaultKind.FORWARD_HEAD).reason.lower()

    def test_every_routine_ends_by_getting_out_of_the_chair(self):
        for fault in [*FaultKind, None]:
            assert routine_for(fault).exercises[-1] is STAND_AND_WALK

    def test_a_clean_day_still_gets_a_break_routine(self):
        routine = routine_for(None)
        assert routine.exercises
        assert routine.seconds > 0


class TestBreakTimer:
    def test_becomes_due_after_the_interval_of_present_time(self):
        timer = BreakTimer(interval_minutes=1)
        fired = [timer.update(present=True, now=t) for t in range(0, 70)]
        assert fired.count(True) == 1
        assert timer.due

    def test_time_away_from_the_desk_does_not_count(self):
        """Otherwise you return from lunch to an instant break prompt."""
        timer = BreakTimer(interval_minutes=1)
        for t in range(0, 200):
            timer.update(present=False, now=t)
        assert not timer.due

    def test_a_long_gap_is_not_banked_as_worked_time(self):
        """Laptop asleep for an hour is not an hour at the desk."""
        timer = BreakTimer(interval_minutes=1)
        timer.update(present=True, now=0)
        timer.update(present=True, now=3600)
        assert not timer.due

    def test_taking_the_break_starts_the_next_interval(self):
        timer = BreakTimer(interval_minutes=1)
        for t in range(0, 70):
            timer.update(present=True, now=t)
        timer.taken()
        assert not timer.due
        assert timer.seconds_until_due == pytest.approx(60.0)

    def test_postponing_makes_it_due_again_sooner(self):
        timer = BreakTimer(interval_minutes=10)
        for t in range(0, 700):
            timer.update(present=True, now=t)
        timer.postpone(minutes=1)
        assert not timer.due
        assert timer.seconds_until_due == pytest.approx(60.0)

    def test_a_disabled_timer_never_becomes_due(self):
        timer = BreakTimer(interval_minutes=1, enabled=False)
        for t in range(0, 200):
            timer.update(present=True, now=t)
        assert not timer.due
