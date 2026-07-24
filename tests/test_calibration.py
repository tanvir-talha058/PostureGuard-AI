import pytest

from postureguard.calibration import Baseline, BaselineBuilder, DriftTracker, baseline_from
from postureguard.metrics import PostureMetrics


def sample(**overrides) -> PostureMetrics:
    return PostureMetrics(
        **{
            "head_shoulder_gap": 0.667,
            "face_scale": 0.300,
            "screen_distance": 0.090,
            "shoulder_roll": 0.0,
            "eye_roll": 0.0,
            "torso_angle": 0.0,
            "shoulder_height": 0.620,
            **overrides,
        }
    )


class TestBaselineBuilder:
    def test_takes_the_median_not_the_mean(self):
        """A single bad detection during calibration must not skew the reference."""
        builder = BaselineBuilder()
        for value in (0.60, 0.62, 0.61, 0.63, 9.99):
            builder.add(sample(head_shoulder_gap=value))
        assert builder.build(minimum=1).get("head_shoulder_gap") == pytest.approx(0.62)

    def test_empty_frames_are_not_counted(self):
        builder = BaselineBuilder()
        for _ in range(10):
            builder.add(PostureMetrics())
        assert builder.frames == 0
        assert not builder.ready(minimum=1)

    def test_intermittent_metrics_are_dropped(self):
        """A hip glimpsed twice between desk and elbow is not a usable reference."""
        builder = BaselineBuilder()
        for i in range(20):
            builder.add(sample(torso_angle=3.0 if i < 2 else None))
        built = builder.build(minimum=10)
        assert built.get("head_shoulder_gap") is not None
        assert built.get("torso_angle") is None

    def test_ready_gates_on_sample_count(self):
        builder = BaselineBuilder()
        for _ in range(5):
            builder.add(sample())
        assert builder.ready(minimum=5)
        assert not builder.ready(minimum=6)


class TestPersistence:
    def test_round_trips_through_disk(self, tmp_path):
        original = baseline_from([sample()])
        path = tmp_path / "nested" / "baseline.json"
        original.save(path)
        loaded = Baseline.load(path)
        assert loaded is not None
        assert loaded.values == original.values

    def test_a_missing_file_returns_none(self, tmp_path):
        assert Baseline.load(tmp_path / "absent.json") is None

    def test_a_corrupt_file_returns_none_instead_of_crashing(self, tmp_path):
        """Startup should send the user to recalibration, not to a traceback."""
        path = tmp_path / "baseline.json"
        path.write_text("{ not json", encoding="utf-8")
        assert Baseline.load(path) is None

    def test_a_well_formed_file_missing_values_returns_none(self, tmp_path):
        path = tmp_path / "baseline.json"
        path.write_text('{"sample_count": 3}', encoding="utf-8")
        assert Baseline.load(path) is None

    def test_records_when_it_was_captured(self):
        assert baseline_from([sample()]).captured_at


class TestDriftTracker:
    def test_stays_silent_until_it_has_enough_history(self):
        tracker = DriftTracker(window_seconds=100, min_samples=10)
        for i in range(9):
            tracker.add(sample(), now=float(i))
        assert tracker.medians() == {}

    def test_reports_medians_once_warmed_up(self):
        tracker = DriftTracker(window_seconds=100, min_samples=10)
        for i in range(20):
            tracker.add(sample(), now=float(i))
        assert tracker.medians()["shoulder_height"] == pytest.approx(0.620)

    def test_old_samples_fall_out_of_the_window(self):
        """Only the recent past should shape the drift picture."""
        tracker = DriftTracker(window_seconds=10, min_samples=5)
        for i in range(10):
            tracker.add(sample(shoulder_height=0.620), now=float(i))
        for i in range(10, 30):
            tracker.add(sample(shoulder_height=0.700), now=float(i))
        assert tracker.medians()["shoulder_height"] == pytest.approx(0.700)

    def test_reset_clears_history(self):
        tracker = DriftTracker(window_seconds=100, min_samples=5)
        for i in range(20):
            tracker.add(sample(), now=float(i))
        tracker.reset()
        assert tracker.medians() == {}

    def test_frames_with_no_detection_are_ignored(self):
        tracker = DriftTracker(window_seconds=100, min_samples=5)
        for i in range(20):
            tracker.add(PostureMetrics(), now=float(i))
        assert tracker.medians() == {}
