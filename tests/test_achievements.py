from datetime import date, timedelta

import pytest

from postureguard.achievements import compute_achievements
from postureguard.calibration import Baseline
from postureguard.session import SessionStore

from test_session import CRANING, TILTING, fill

TODAY = date(2026, 7, 25)


@pytest.fixture
def store():
    with SessionStore() as s:
        yield s


class TestAchievements:
    def test_five_fixed_milestones_none_earned_on_empty_history(self, store):
        achievements = compute_achievements(store, baseline=None, today=TODAY)
        assert [a.key for a in achievements] == [
            "first_calibration",
            "first_clean_day",
            "streak_7",
            "streak_30",
            "most_improved",
        ]
        assert all(not a.earned for a in achievements)

    def test_first_calibration_earned_once_a_baseline_exists(self, store):
        baseline = Baseline(values={"forward_head_ratio": 0.1}, sample_count=30, captured_at="2026-07-01")
        achievements = compute_achievements(store, baseline=baseline, today=TODAY)
        by_key = {a.key: a for a in achievements}
        assert by_key["first_calibration"].earned

    def test_first_clean_day_earned_after_one_good_day(self, store):
        fill(store, TODAY, 9, 1800, "in_tolerance")
        achievements = compute_achievements(store, baseline=None, today=TODAY)
        by_key = {a.key: a for a in achievements}
        assert by_key["first_clean_day"].earned

    def test_streak_milestones_earned_at_the_right_length(self, store):
        for offset in range(7):
            fill(store, TODAY - timedelta(days=offset), 9, 1800, "in_tolerance")
        achievements = compute_achievements(store, baseline=None, today=TODAY)
        by_key = {a.key: a for a in achievements}
        assert by_key["streak_7"].earned
        assert not by_key["streak_30"].earned

    def test_most_improved_reflects_the_weekly_trend(self, store):
        for offset in range(7):
            fill(store, TODAY - timedelta(days=offset), 9, 3600, "in_tolerance")
        for offset in range(7, 14):
            fill(store, TODAY - timedelta(days=offset), 10, 600, "fault", CRANING)

        achievements = compute_achievements(store, baseline=None, today=TODAY)
        by_key = {a.key: a for a in achievements}
        assert by_key["most_improved"].earned
        assert "forward head" in by_key["most_improved"].description.lower()
