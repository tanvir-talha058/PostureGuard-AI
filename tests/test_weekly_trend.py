from datetime import date, timedelta

import pytest

from postureguard.rules import FaultKind
from postureguard.session import SessionStore
from postureguard.weekly_trend import compute_weekly_trend

from test_session import CRANING, TILTING, fill  # reuse existing fixtures/helpers

TODAY = date(2026, 7, 25)


@pytest.fixture
def store():
    with SessionStore() as s:
        yield s


class TestWeeklyTrend:
    def test_none_when_not_enough_data_either_week(self, store):
        fill(store, TODAY, 9, 60, "in_tolerance")
        assert compute_weekly_trend(store, today=TODAY) is None

    def test_none_when_this_week_has_data_but_last_week_does_not(self, store):
        for offset in range(7):
            fill(store, TODAY - timedelta(days=offset), 9, 3600, "in_tolerance")
        assert compute_weekly_trend(store, today=TODAY) is None

    def test_compares_averages_across_adjacent_weeks(self, store):
        for offset in range(7):
            fill(store, TODAY - timedelta(days=offset), 9, 3600, "in_tolerance")
        for offset in range(7, 14):
            fill(store, TODAY - timedelta(days=offset), 9, 1800, "in_tolerance")
            fill(store, TODAY - timedelta(days=offset), 10, 1800, "fault", CRANING)

        trend = compute_weekly_trend(store, today=TODAY)

        assert trend is not None
        assert trend.this_week_average == pytest.approx(100.0)
        assert trend.last_week_average == pytest.approx(50.0)

    def test_finds_the_fault_that_dropped_the_most(self, store):
        for offset in range(7):
            fill(store, TODAY - timedelta(days=offset), 9, 3600, "in_tolerance")
        for offset in range(7, 14):
            fill(store, TODAY - timedelta(days=offset), 10, 600, "fault", CRANING)
            fill(store, TODAY - timedelta(days=offset), 11, 100, "fault", TILTING)

        trend = compute_weekly_trend(store, today=TODAY)

        assert trend.most_improved_fault == FaultKind.FORWARD_HEAD
        assert trend.most_improved_seconds == 7 * 600
