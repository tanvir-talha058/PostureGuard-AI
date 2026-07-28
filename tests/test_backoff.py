from datetime import date

from postureguard.backoff import BACKOFF_STEP, MIN_SENSITIVITY, SNOOZE_THRESHOLD, SnoozeBackoff

DAY = date(2026, 7, 25)


class TestRecord:
    def test_returns_false_below_the_threshold(self):
        backoff = SnoozeBackoff()
        results = [backoff.record(DAY) for _ in range(SNOOZE_THRESHOLD - 1)]
        assert not any(results)

    def test_returns_true_exactly_on_the_threshold(self):
        backoff = SnoozeBackoff()
        results = [backoff.record(DAY) for _ in range(SNOOZE_THRESHOLD)]
        assert results == [False] * (SNOOZE_THRESHOLD - 1) + [True]

    def test_does_not_retrigger_later_the_same_day(self):
        backoff = SnoozeBackoff()
        for _ in range(SNOOZE_THRESHOLD):
            backoff.record(DAY)
        later = [backoff.record(DAY) for _ in range(5)]
        assert not any(later)

    def test_a_new_day_resets_the_count(self):
        backoff = SnoozeBackoff()
        for _ in range(SNOOZE_THRESHOLD):
            backoff.record(DAY)
        from datetime import timedelta

        tomorrow = DAY + timedelta(days=1)
        results = [backoff.record(tomorrow) for _ in range(SNOOZE_THRESHOLD)]
        assert results == [False] * (SNOOZE_THRESHOLD - 1) + [True]


class TestNextSensitivity:
    def test_steps_down_by_the_backoff_amount(self):
        assert SnoozeBackoff.next_sensitivity(1.0) == round(1.0 - BACKOFF_STEP, 2)

    def test_never_drops_below_the_floor(self):
        assert SnoozeBackoff.next_sensitivity(MIN_SENSITIVITY) == MIN_SENSITIVITY
        assert SnoozeBackoff.next_sensitivity(0.3) == MIN_SENSITIVITY


class TestPersistence:
    def test_round_trips_through_a_file(self, tmp_path):
        backoff = SnoozeBackoff()
        backoff.record(DAY)
        backoff.record(DAY)
        path = tmp_path / "snooze_backoff.json"
        backoff.save_state(path)

        restored = SnoozeBackoff.load(path)
        assert restored.day == DAY.isoformat()
        assert restored.count == 2

    def test_missing_file_loads_a_fresh_state(self, tmp_path):
        restored = SnoozeBackoff.load(tmp_path / "missing.json")
        assert restored.day == ""
        assert restored.count == 0

    def test_corrupt_file_loads_a_fresh_state(self, tmp_path):
        path = tmp_path / "snooze_backoff.json"
        path.write_text("not json", encoding="utf-8")
        restored = SnoozeBackoff.load(path)
        assert restored.count == 0
