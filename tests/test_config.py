import pytest

from postureguard.config import Config
from postureguard.rules import Thresholds


class TestSensitivity:
    def test_default_sensitivity_reproduces_the_baseline_thresholds(self):
        assert Config().thresholds().forward_head_gap_drop == pytest.approx(
            Thresholds().forward_head_gap_drop
        )

    def test_higher_sensitivity_flags_smaller_deviations(self):
        sensitive = Config(sensitivity=2.0).thresholds()
        assert sensitive.forward_head_gap_drop < Thresholds().forward_head_gap_drop

    def test_lower_sensitivity_is_more_forgiving(self):
        relaxed = Config(sensitivity=0.5).thresholds()
        assert relaxed.forward_head_gap_drop > Thresholds().forward_head_gap_drop

    def test_extreme_sensitivity_is_clamped_to_something_usable(self):
        """A slider at the end stop must not make everything, or nothing, a fault."""
        for value in (0.0, -5.0, 1000.0):
            thresholds = Config(sensitivity=value).thresholds()
            assert 0 < thresholds.forward_head_gap_drop < 1
            assert thresholds.tilt_degrees > 0

    def test_reaction_time_converts_to_frames(self):
        thresholds = Config(react_after_seconds=1.0).thresholds(frame_rate=30)
        assert thresholds.enter_frames == 30

    def test_reaction_time_never_rounds_down_to_zero_frames(self):
        assert Config(react_after_seconds=0.001).thresholds(frame_rate=30).enter_frames == 1
        assert Config(react_after_seconds=0.001).thresholds(frame_rate=30).exit_frames == 1


class TestPersistence:
    def test_round_trips_through_disk(self, tmp_path):
        original = Config(sensitivity=1.4, break_interval_minutes=25, mirror=False)
        path = tmp_path / "nested" / "config.json"
        original.save(path)
        assert Config.load(path) == original

    def test_a_missing_file_yields_defaults(self, tmp_path):
        assert Config.load(tmp_path / "absent.json") == Config()

    def test_a_corrupt_file_yields_defaults_rather_than_crashing(self, tmp_path):
        """Settings are never worth failing startup over."""
        path = tmp_path / "config.json"
        path.write_text("{ not json", encoding="utf-8")
        assert Config.load(path) == Config()

    def test_unknown_keys_from_a_newer_version_are_ignored(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text('{"sensitivity": 1.5, "telepathy_mode": true}', encoding="utf-8")
        loaded = Config.load(path)
        assert loaded.sensitivity == 1.5

    def test_mini_window_settings_round_trip(self, tmp_path):
        path = tmp_path / "config.json"
        Config(mini_window=False, mini_x=1200, mini_y=40).save(path)
        loaded = Config.load(path)
        assert loaded.mini_window is False
        assert (loaded.mini_x, loaded.mini_y) == (1200, 40)

    def test_mini_window_is_on_by_default_and_unplaced(self):
        assert Config().mini_window is True
        assert Config().mini_x == -1 and Config().mini_y == -1

    def test_a_json_file_that_is_not_an_object_yields_defaults(self, tmp_path):
        path = tmp_path / "config.json"
        path.write_text("[1, 2, 3]", encoding="utf-8")
        assert Config.load(path) == Config()
