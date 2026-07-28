import pytest

from postureguard.engine import Engine, Phase
from postureguard.landmarks import Landmarks
from postureguard.rules import FaultKind, Thresholds

from fixtures import ASPECT, SLUMPED, UPRIGHT, Pose, build

FAST = Thresholds(enter_frames=3, exit_frames=2)
EMPTY = Landmarks({})


def drive(engine: Engine, pose_landmarks, seconds: float, start: float = 0.0, fps: int = 30):
    """Feed frames at a fixed rate, returning the last reading."""
    reading = None
    for i in range(int(seconds * fps)):
        reading = engine.process(pose_landmarks, ASPECT, start + i / fps)
    return reading


def calibrated(thresholds: Thresholds = FAST) -> tuple[Engine, float]:
    """Run an engine through calibration; returns it and the clock time reached."""
    engine = Engine(thresholds=thresholds, prep_seconds=1.0, capture_seconds=1.0)
    drive(engine, build(UPRIGHT), seconds=3.0)
    assert engine.phase is Phase.MONITORING
    return engine, 3.0


class TestCalibration:
    def test_starts_in_preparing_without_a_baseline(self):
        assert Engine().phase is Phase.PREPARING

    def test_skips_calibration_when_a_baseline_is_supplied(self):
        engine, _ = calibrated()
        assert Engine(baseline=engine.baseline).phase is Phase.MONITORING

    def test_countdown_does_not_run_against_an_empty_chair(self):
        """Otherwise the app banks a baseline of nothing while the user is at lunch."""
        engine = Engine(prep_seconds=1.0, capture_seconds=1.0)
        reading = drive(engine, EMPTY, seconds=10.0)
        assert engine.phase is Phase.PREPARING
        assert "step into view" in reading.message.lower()

    def test_captures_a_baseline_from_sustained_good_posture(self):
        engine, _ = calibrated()
        assert engine.baseline is not None
        assert engine.baseline.get("head_shoulder_gap") == pytest.approx(0.667, abs=0.01)

    def test_signals_the_frame_the_baseline_lands_so_it_can_be_saved(self):
        engine = Engine(thresholds=FAST, prep_seconds=1.0, capture_seconds=1.0)
        captures = [
            engine.process(build(UPRIGHT), ASPECT, i / 30).baseline_just_captured
            for i in range(90)
        ]
        assert captures.count(True) == 1

    def test_dropped_frames_do_not_restart_the_countdown(self):
        """Live pose detection misses the odd frame. Restarting on each miss meant
        calibration never completed against a real camera."""
        engine = Engine(thresholds=FAST, prep_seconds=1.0, capture_seconds=1.0)
        for i in range(120):  # 4 seconds at 30fps
            # Drop roughly one frame in eight, the way real detection does.
            landmarks = EMPTY if i % 8 == 7 else build(UPRIGHT)
            engine.process(landmarks, ASPECT, i / 30)
        assert engine.phase is Phase.MONITORING
        assert engine.baseline is not None

    def test_a_sustained_absence_does_restart_the_countdown(self):
        engine = Engine(thresholds=FAST, prep_seconds=1.0, capture_seconds=1.0)
        drive(engine, build(UPRIGHT), seconds=1.2)
        reading = drive(engine, EMPTY, seconds=3.0, start=1.2)
        assert engine.phase is Phase.PREPARING
        assert "step into view" in reading.message.lower()

    def test_walking_away_mid_capture_discards_the_partial_baseline(self):
        """Half a baseline is worse than none — it silently miscalibrates everything."""
        engine = Engine(thresholds=FAST, prep_seconds=1.0, capture_seconds=5.0)
        drive(engine, build(UPRIGHT), seconds=3.0)
        drive(engine, EMPTY, seconds=3.0, start=3.0)
        assert engine.phase is Phase.PREPARING
        assert engine.baseline is None

    def test_recalibrate_returns_to_preparing(self):
        engine, _ = calibrated()
        engine.recalibrate()
        assert engine.phase is Phase.PREPARING


class TestMonitoring:
    def test_good_posture_reads_in_tolerance(self):
        engine, t = calibrated()
        assert drive(engine, build(UPRIGHT), seconds=2.0, start=t).status == "in_tolerance"

    def test_sustained_craning_raises_a_fault(self):
        engine, t = calibrated()
        reading = drive(engine, build(SLUMPED), seconds=2.0, start=t)
        assert reading.status == "fault"
        assert FaultKind.FORWARD_HEAD in {f.kind for f in reading.faults}

    def test_correcting_posture_returns_to_tolerance(self):
        engine, t = calibrated()
        drive(engine, build(SLUMPED), seconds=2.0, start=t)
        assert drive(engine, build(UPRIGHT), seconds=2.0, start=t + 2).status == "in_tolerance"

    def test_losing_the_subject_reads_as_searching(self):
        engine, t = calibrated()
        reading = drive(engine, EMPTY, seconds=2.0, start=t)
        assert reading.status == "searching"
        assert reading.faults == []

    def test_moving_the_chair_back_is_not_a_fault(self):
        engine, t = calibrated()
        reading = drive(engine, build(UPRIGHT.scaled(0.8)), seconds=3.0, start=t)
        assert reading.status == "in_tolerance"

    def test_every_fault_reading_carries_an_instruction(self):
        engine, t = calibrated()
        reading = drive(engine, build(SLUMPED), seconds=2.0, start=t)
        assert all(f.cue.strip() for f in reading.faults)


class TestSnooze:
    def test_snoozing_suppresses_the_fault_status(self):
        engine, t = calibrated()
        drive(engine, build(SLUMPED), seconds=2.0, start=t)
        engine.snooze(300, now=t + 2)
        assert drive(engine, build(SLUMPED), seconds=1.0, start=t + 2).status == "snoozed"

    def test_faults_return_once_the_snooze_expires(self):
        engine, t = calibrated()
        engine.snooze(1.0, now=t)
        assert drive(engine, build(SLUMPED), seconds=3.0, start=t + 1.5).status == "fault"


class TestStanding:
    def test_standing_up_reports_standing_and_suspends_checks(self):
        engine, t = calibrated()
        reading = drive(engine, build(Pose(shoulder_y=0.40)), seconds=2.0, start=t)
        assert reading.status == "standing"
        assert reading.faults == []

    def test_a_small_rise_is_not_mistaken_for_standing(self):
        """Far short of the threshold — an ordinary posture shift, not standing up."""
        engine, t = calibrated()
        reading = drive(engine, build(Pose(shoulder_y=0.55)), seconds=2.0, start=t)
        assert reading.status != "standing"

    def test_sitting_back_down_resumes_checks(self):
        engine, t = calibrated()
        drive(engine, build(Pose(shoulder_y=0.40)), seconds=2.0, start=t)
        reading = drive(engine, build(SLUMPED), seconds=2.0, start=t + 2)
        assert reading.status == "fault"
        assert FaultKind.FORWARD_HEAD in {f.kind for f in reading.faults}

    def test_disabling_it_never_reports_standing(self):
        engine, t = calibrated()
        engine.standing_detection_enabled = False
        reading = drive(engine, build(Pose(shoulder_y=0.40)), seconds=2.0, start=t)
        assert reading.status != "standing"

    def test_standing_time_is_not_counted_as_measurable_presence_for_drift(self):
        """Standing must not silently bank samples into the sitting drift window."""
        engine, t = calibrated()
        drive(engine, build(Pose(shoulder_y=0.40)), seconds=5.0, start=t)
        reading = drive(engine, build(UPRIGHT), seconds=1.0, start=t + 5)
        assert FaultKind.DRIFT not in {f.kind for f in reading.faults}


class TestDrift:
    def test_slow_sinking_is_caught_even_without_an_instant_fault(self):
        """The afternoon slide: never past a threshold, but worse than baseline."""
        engine, t = calibrated()
        # A sink small enough to stay inside the instantaneous threshold.
        barely = build(Pose(shoulder_y=0.653))
        reading = drive(engine, barely, seconds=40.0, start=t, fps=30)
        assert FaultKind.DRIFT in {f.kind for f in reading.faults}
        assert reading.status == "drifting"

    def test_holding_the_baseline_never_reports_drift(self):
        engine, t = calibrated()
        reading = drive(engine, build(UPRIGHT), seconds=40.0, start=t, fps=30)
        assert FaultKind.DRIFT not in {f.kind for f in reading.faults}
