from datetime import date

import pytest

from postureguard.ai.weekly_summary import build_stats_payload, generate_message
from postureguard.session import SessionStore

TODAY = date(2026, 8, 2)


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


class TestBuildStatsPayload:
    def test_none_when_too_little_was_tracked(self, store):
        fill(store, TODAY, 10, 30, "in_tolerance")
        assert build_stats_payload(store, today=TODAY) is None

    def test_names_average_and_worst_hour(self, store):
        fill(store, TODAY, 9, 3600, "in_tolerance")
        fill(store, TODAY, 15, 3600, "fault")
        payload = build_stats_payload(store, today=TODAY)
        assert payload is not None
        assert payload["worst_hour"] == "15:00"
        assert payload["average_in_tolerance_percent"] == pytest.approx(50.0, abs=1.0)

    def test_no_camera_or_metric_data_in_the_payload(self, store):
        fill(store, TODAY, 9, 3600, "in_tolerance")
        fill(store, TODAY, 15, 3600, "fault")
        payload = build_stats_payload(store, today=TODAY)
        assert "frame" not in str(payload).lower()
        assert "landmark" not in str(payload).lower()
        assert set(payload.keys()) == {
            "days_tracked",
            "average_in_tolerance_percent",
            "worst_hour",
            "worst_hour_score_percent",
            "fault_minutes",
        }


class TestGenerateMessage:
    def test_returns_none_when_ask_fails(self, monkeypatch):
        monkeypatch.setattr("postureguard.ai.weekly_summary.ask", lambda *a, **k: None)
        assert generate_message({"average_in_tolerance_percent": 80.0}, "sk-ant-test") is None

    def test_sends_the_payload_as_json_content(self, monkeypatch):
        captured = {}

        def _fake_ask(system, content, api_key, **kwargs):
            captured["system"] = system
            captured["content"] = content
            captured["api_key"] = api_key
            return "You averaged 80% this week."

        monkeypatch.setattr("postureguard.ai.weekly_summary.ask", _fake_ask)
        payload = {"average_in_tolerance_percent": 80.0}
        result = generate_message(payload, "sk-ant-test")
        assert result == "You averaged 80% this week."
        assert captured["api_key"] == "sk-ant-test"
        assert "80.0" in captured["content"]
