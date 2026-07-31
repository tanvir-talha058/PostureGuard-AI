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
            FaultKind.SCREEN_TOO_FAR,
            FaultKind.HEAD_ROTATION,
            FaultKind.SHOULDER_SHRUG,
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


class TestBreakTimerPersistence:
    def test_a_recent_save_restores_the_banked_time(self):
        timer = BreakTimer(interval_minutes=10)
        for t in range(0, 121):  # 120s worked, ticked like the real controller does
            timer.update(present=True, now=t)
        assert timer._worked == pytest.approx(120.0)

        state = timer.to_state()
        restored = BreakTimer.restore(
            state, interval_minutes=10, enabled=True, now_wall=state["saved_at"] + 5
        )
        for t in range(0, 11):  # +10s worked, one second at a time
            restored.update(present=True, now=t)
        assert restored.seconds_until_due == pytest.approx(600 - 130, abs=0.5)

    def test_a_stale_save_is_discarded(self):
        """The user has clearly been away; the pre-gap progress should not just
        resume counting as if nothing happened."""
        from postureguard.stretches import BREAK_STATE_STALE_AFTER_SECONDS

        timer = BreakTimer(interval_minutes=10)
        for t in range(0, 301):
            timer.update(present=True, now=t)

        state = timer.to_state()
        restored = BreakTimer.restore(
            state,
            interval_minutes=10,
            enabled=True,
            now_wall=state["saved_at"] + BREAK_STATE_STALE_AFTER_SECONDS + 1,
        )
        assert restored.seconds_until_due == pytest.approx(600.0)

    def test_a_save_from_the_future_is_also_discarded(self):
        """A clock that moved backwards (DST, manual change) must not be trusted
        into crediting time that has not happened yet."""
        timer = BreakTimer(interval_minutes=10)
        for t in range(0, 121):
            timer.update(present=True, now=t)

        state = timer.to_state()
        restored = BreakTimer.restore(
            state, interval_minutes=10, enabled=True, now_wall=state["saved_at"] - 10
        )
        assert restored.seconds_until_due == pytest.approx(600.0)

    def test_restoring_does_not_immediately_fire_due_before_a_real_tick(self):
        """A restore that lands already over the interval must wait for the next
        genuine update() before announcing it, the same as a fresh timer would."""
        timer = BreakTimer(interval_minutes=1)
        for t in range(0, 65):  # ticks past the 60s interval, one second at a time
            timer.update(present=True, now=t)
        assert timer._worked > timer.interval_seconds
        state = timer.to_state()

        # restore() only carries `worked_seconds` across, never `_due` — so the
        # restored timer starts as if it has not yet noticed it is over interval.
        restored = BreakTimer.restore(
            state, interval_minutes=1, enabled=True, now_wall=state["saved_at"]
        )
        assert restored.update(present=True, now=0) is False  # baseline tick only
        assert restored.update(present=True, now=1) is True  # now it announces

    def test_restoring_ignores_a_monotonic_clock_from_the_old_process(self):
        """_last_tick must never be restored — it is only meaningful within the
        process that produced it."""
        timer = BreakTimer(interval_minutes=10)
        timer.update(present=True, now=99999.0)
        state = timer.to_state()

        restored = BreakTimer.restore(
            state, interval_minutes=10, enabled=True, now_wall=state["saved_at"]
        )
        # A fresh process's monotonic clock starts near zero; if the old _last_tick
        # had survived, this update would compute an enormous negative delta.
        assert restored.update(present=True, now=1.0) is False
        assert restored.seconds_until_due <= 600.0

    def test_round_trips_through_disk(self, tmp_path):
        path = tmp_path / "break_state.json"
        timer = BreakTimer(interval_minutes=10)
        for t in range(0, 121):
            timer.update(present=True, now=t)
        timer.save_state(path)

        restored = BreakTimer.load_restored(path, interval_minutes=10, enabled=True)
        restored.update(present=True, now=0)
        restored.update(present=True, now=1)
        assert restored.seconds_until_due < 600.0

    def test_a_missing_file_yields_a_fresh_timer(self, tmp_path):
        restored = BreakTimer.load_restored(
            tmp_path / "absent.json", interval_minutes=10, enabled=True
        )
        assert restored.seconds_until_due == pytest.approx(600.0)

    def test_a_corrupt_file_yields_a_fresh_timer_rather_than_crashing(self, tmp_path):
        path = tmp_path / "break_state.json"
        path.write_text("{ not json", encoding="utf-8")
        restored = BreakTimer.load_restored(path, interval_minutes=10, enabled=True)
        assert restored.seconds_until_due == pytest.approx(600.0)

    def test_malformed_state_shapes_yield_a_fresh_timer(self, tmp_path):
        for payload in ('"just a string"', "[1, 2, 3]", '{"worked_seconds": "oops"}'):
            path = tmp_path / "break_state.json"
            path.write_text(payload, encoding="utf-8")
            restored = BreakTimer.load_restored(path, interval_minutes=10, enabled=True)
            assert restored.seconds_until_due == pytest.approx(600.0)
