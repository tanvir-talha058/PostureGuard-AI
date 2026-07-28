from datetime import date, timedelta

import pytest

from postureguard.session import SessionStore
from postureguard.weekly_summary import WeeklySummaryGate, build_message

TODAY = date(2026, 7, 25)


def at(day: date, hour: int = 10, second: int = 0) -> float:
    from datetime import datetime

    return datetime(day.year, day.month, day.day, hour).timestamp() + second


def fill(store: SessionStore, day: date, hour: int, seconds: int, status: str, faults=()):
    for s in range(seconds):
        store.log(status, faults, when=at(day, hour, s))


@pytest.fixture
def store():
    with SessionStore() as s:
        yield s


class TestGateDue:
    def test_never_due_with_no_prior_summary(self):
        assert WeeklySummaryGate().due(TODAY) is False

    def test_not_due_before_the_interval_elapses(self):
        gate = WeeklySummaryGate(last_shown=(TODAY - timedelta(days=3)).isoformat())
        assert gate.due(TODAY) is False

    def test_due_once_the_interval_elapses(self):
        gate = WeeklySummaryGate(last_shown=(TODAY - timedelta(days=7)).isoformat())
        assert gate.due(TODAY) is True

    def test_mark_shown_resets_the_anchor(self):
        gate = WeeklySummaryGate(last_shown=(TODAY - timedelta(days=7)).isoformat())
        gate.mark_shown(TODAY)
        assert gate.due(TODAY) is False
        assert gate.due(TODAY + timedelta(days=7)) is True


class TestGatePersistence:
    def test_round_trips_through_a_file(self, tmp_path):
        gate = WeeklySummaryGate(last_shown=TODAY.isoformat())
        path = tmp_path / "weekly_summary.json"
        gate.save_state(path)
        assert WeeklySummaryGate.load(path).last_shown == TODAY.isoformat()

    def test_missing_file_loads_a_fresh_gate(self, tmp_path):
        assert WeeklySummaryGate.load(tmp_path / "missing.json").last_shown == ""

    def test_corrupt_file_loads_a_fresh_gate(self, tmp_path):
        path = tmp_path / "weekly_summary.json"
        path.write_text("not json", encoding="utf-8")
        assert WeeklySummaryGate.load(path).last_shown == ""


class TestBuildMessage:
    def test_none_when_too_little_was_tracked(self, store):
        fill(store, TODAY, 10, 30, "in_tolerance")
        assert build_message(store, TODAY) is None

    def test_names_the_average_and_the_worst_hour(self, store):
        fill(store, TODAY, 9, 3600, "in_tolerance")
        fill(store, TODAY, 15, 3600, "fault")
        message = build_message(store, TODAY)
        assert message is not None
        assert "15:00" in message
        assert "%" in message
