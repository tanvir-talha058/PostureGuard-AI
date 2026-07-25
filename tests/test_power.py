"""Activity/power probe logic.

The public functions are tested by monkeypatching the private single-purpose calls
they wrap, so the suite runs the same on any platform without a real locked session
or a battery to unplug.
"""

from __future__ import annotations

from postureguard import power


class TestIdleSeconds:
    def test_reports_the_gap_between_last_input_and_now(self, monkeypatch):
        monkeypatch.setattr(power, "_get_last_input_tick", lambda: 1000)
        monkeypatch.setattr(power, "_get_tick_count", lambda: 5500)
        assert power.idle_seconds() == 4.5

    def test_zero_when_input_was_just_now(self, monkeypatch):
        monkeypatch.setattr(power, "_get_last_input_tick", lambda: 5000)
        monkeypatch.setattr(power, "_get_tick_count", lambda: 5000)
        assert power.idle_seconds() == 0.0

    def test_never_goes_negative_on_a_wrapped_tick_counter(self, monkeypatch):
        """GetTickCount wraps roughly every 49 days; a stale last-input tick just
        after a wrap must not report a negative idle time."""
        monkeypatch.setattr(power, "_get_last_input_tick", lambda: 4_000_000_000)
        monkeypatch.setattr(power, "_get_tick_count", lambda: 100)
        assert power.idle_seconds() == 0.0

    def test_unsupported_platform_reports_never_idle(self, monkeypatch):
        """No signal available means never pause, not always pause."""
        monkeypatch.setattr(power, "_get_last_input_tick", lambda: None)
        assert power.idle_seconds() == 0.0


class TestSessionLocked:
    def test_locked_when_the_input_desktop_cannot_be_opened(self, monkeypatch):
        monkeypatch.setattr(power, "_can_open_input_desktop", lambda: False)
        assert power.session_locked() is True

    def test_unlocked_when_it_opens_fine(self, monkeypatch):
        monkeypatch.setattr(power, "_can_open_input_desktop", lambda: True)
        assert power.session_locked() is False

    def test_unsupported_platform_reports_unlocked(self, monkeypatch):
        monkeypatch.setattr(power, "_can_open_input_desktop", lambda: None)
        assert power.session_locked() is False


class TestOnBattery:
    def test_true_only_on_a_confirmed_battery_reading(self, monkeypatch):
        monkeypatch.setattr(power, "_ac_line_status", lambda: 0)
        assert power.on_battery() is True

    def test_false_when_plugged_in(self, monkeypatch):
        monkeypatch.setattr(power, "_ac_line_status", lambda: 1)
        assert power.on_battery() is False

    def test_false_when_unknown_rather_than_guessing(self, monkeypatch):
        monkeypatch.setattr(power, "_ac_line_status", lambda: 255)
        assert power.on_battery() is False

    def test_false_when_unsupported(self, monkeypatch):
        monkeypatch.setattr(power, "_ac_line_status", lambda: None)
        assert power.on_battery() is False
