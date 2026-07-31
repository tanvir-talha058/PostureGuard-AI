
from postureguard.calibration import baseline_from
from postureguard.metrics import PostureMetrics
from postureguard.rules import FaultKind, RuleEngine, Thresholds, evaluate_drift

GOOD = PostureMetrics(
    head_shoulder_gap=0.667,
    face_scale=0.300,
    screen_distance=0.090,
    shoulder_roll=0.0,
    eye_roll=0.0,
    torso_angle=0.0,
    shoulder_height=0.620,
    head_yaw=0.0,
)

BASELINE = baseline_from([GOOD])
# Frame-equivalent at the default dt (NOMINAL_FRAME_SECONDS = 1/30s), so `run()`
# feeding N calls at the default dt behaves exactly like the old frame-counted debounce.
FAST = Thresholds(enter_seconds=3 / 30, exit_seconds=2 / 30)


def metrics(**overrides) -> PostureMetrics:
    return PostureMetrics(**{**GOOD.as_dict(), **overrides})


def run(engine: RuleEngine, sample: PostureMetrics, frames: int):
    """Feed the same sample repeatedly, returning the faults after the last frame."""
    result = []
    for _ in range(frames):
        result = engine.update(sample)
    return result


def kinds(faults):
    return {f.kind for f in faults}


# Craning: the gap closes while the face grows.
CRANING = metrics(head_shoulder_gap=0.333, face_scale=0.367)
# Chair pushed back far enough (a 20% drop) to be its own fault, not just a shift.
FURTHER = metrics(screen_distance=0.072)
# A small chair-back shift — inside the dead zone, not a fault either direction.
SLIGHTLY_FURTHER = metrics(screen_distance=0.086)
# Whole body leaned in: absolutes grow, ratios hold.
LEANING_IN = metrics(screen_distance=0.126)
# Collapsed into the chair.
SUNK = metrics(shoulder_height=0.700, torso_angle=0.0)


class TestGoodPosture:
    def test_baseline_posture_never_faults(self):
        engine = RuleEngine(BASELINE, FAST)
        assert run(engine, GOOD, 100) == []

    def test_small_wobble_stays_quiet(self):
        engine = RuleEngine(BASELINE, FAST)
        wobble = metrics(head_shoulder_gap=0.650, eye_roll=2.0)
        assert run(engine, wobble, 100) == []


class TestDebounce:
    def test_a_fault_needs_sustained_evidence(self):
        engine = RuleEngine(BASELINE, FAST)
        assert engine.update(CRANING) == []
        assert engine.update(CRANING) == []
        assert FaultKind.FORWARD_HEAD in kinds(engine.update(CRANING))

    def test_a_brief_lapse_never_fires(self):
        engine = RuleEngine(BASELINE, FAST)
        for _ in range(20):
            engine.update(CRANING)
            engine.update(CRANING)  # two bad frames, short of the three required
            assert engine.update(GOOD) == []

    def test_correcting_posture_clears_the_fault(self):
        engine = RuleEngine(BASELINE, FAST)
        run(engine, CRANING, 5)
        assert FaultKind.FORWARD_HEAD in engine.active
        run(engine, GOOD, 5)
        assert engine.active == frozenset()


class TestHysteresis:
    def test_oscillating_at_the_threshold_does_not_flap(self):
        """The whole point of hysteresis: alert once, not fifty times."""
        engine = RuleEngine(BASELINE, FAST)
        run(engine, CRANING, 5)
        assert FaultKind.FORWARD_HEAD in engine.active

        # Now hover around the entry threshold — crossing back and forth, but never
        # dropping under the 0.8x exit threshold.
        just_over = metrics(head_shoulder_gap=0.560, face_scale=0.322)
        just_under = metrics(head_shoulder_gap=0.575, face_scale=0.320)

        deactivations, was_active = 0, True
        for i in range(60):
            faults = engine.update(just_over if i % 2 == 0 else just_under)
            now_active = FaultKind.FORWARD_HEAD in kinds(faults)
            if was_active and not now_active:
                deactivations += 1
            was_active = now_active

        assert deactivations == 0
        assert was_active, "should still be active at the end, not flickering off"

    def test_a_single_jittery_frame_does_not_clear_an_active_fault(self):
        engine = RuleEngine(BASELINE, FAST)
        run(engine, CRANING, 5)
        engine.update(GOOD)
        assert FaultKind.FORWARD_HEAD in engine.active

    def test_entry_threshold_is_higher_than_exit_threshold(self):
        engine = RuleEngine(BASELINE, FAST)
        run(engine, CRANING, 5)
        # Recovered past the exit threshold but not all the way to baseline.
        partial = metrics(head_shoulder_gap=0.600, face_scale=0.312)
        run(engine, partial, 5)
        assert FaultKind.FORWARD_HEAD not in engine.active


class TestForwardHeadDisambiguation:
    def test_a_small_chair_shift_back_is_not_bad_posture(self):
        engine = RuleEngine(BASELINE, FAST)
        assert run(engine, SLIGHTLY_FURTHER, 30) == []

    def test_moving_the_chair_back_far_enough_flags_too_far_not_forward_head(self):
        """A real, sustained retreat is its own fault — not silence, and not forward
        head, which needs the opposite (closing) gap signal."""
        engine = RuleEngine(BASELINE, FAST)
        faults = run(engine, FURTHER, 30)
        assert FaultKind.SCREEN_TOO_FAR in kinds(faults)
        assert FaultKind.FORWARD_HEAD not in kinds(faults)

    def test_leaning_in_flags_distance_not_forward_head(self):
        """Both signals move, but the ratios do not — so it is distance, not craning."""
        engine = RuleEngine(BASELINE, FAST)
        faults = run(engine, LEANING_IN, 30)
        assert FaultKind.SCREEN_TOO_CLOSE in kinds(faults)
        assert FaultKind.FORWARD_HEAD not in kinds(faults)

    def test_gap_dropping_alone_is_not_enough(self):
        """One signal without the other is ambiguous and must not fire."""
        engine = RuleEngine(BASELINE, FAST)
        assert FaultKind.FORWARD_HEAD not in kinds(
            run(engine, metrics(head_shoulder_gap=0.333), 30)
        )

    def test_face_growing_alone_is_not_enough(self):
        engine = RuleEngine(BASELINE, FAST)
        assert FaultKind.FORWARD_HEAD not in kinds(
            run(engine, metrics(face_scale=0.400), 30)
        )


class TestScreenTooFar:
    """The symmetric counterpart to too-close: reused thresholds structure, opposite
    direction — see rules._screen_too_far."""

    def test_a_sustained_retreat_flags_too_far(self):
        engine = RuleEngine(BASELINE, FAST)
        assert FaultKind.SCREEN_TOO_FAR in kinds(run(engine, FURTHER, 30))

    def test_a_small_retreat_stays_quiet(self):
        engine = RuleEngine(BASELINE, FAST)
        assert run(engine, SLIGHTLY_FURTHER, 30) == []

    def test_too_far_and_too_close_are_mutually_exclusive(self):
        engine = RuleEngine(BASELINE, FAST)
        assert FaultKind.SCREEN_TOO_CLOSE not in kinds(run(engine, FURTHER, 30))

        engine = RuleEngine(BASELINE, FAST)
        assert FaultKind.SCREEN_TOO_FAR not in kinds(run(engine, LEANING_IN, 30))

    def test_correcting_back_toward_baseline_clears_the_fault(self):
        engine = RuleEngine(BASELINE, FAST)
        run(engine, FURTHER, 5)
        assert FaultKind.SCREEN_TOO_FAR in engine.active
        run(engine, GOOD, 5)
        assert engine.active == frozenset()

    def test_slow_drift_further_from_the_screen_is_reported_as_drift(self):
        further_dict = {**GOOD.as_dict(), "screen_distance": FURTHER.screen_distance}
        fault = evaluate_drift(BASELINE, further_dict, Thresholds())
        assert fault is not None and fault.kind == FaultKind.DRIFT


class TestOtherFaults:
    def test_sinking_in_the_chair_flags_spine_flexion(self):
        engine = RuleEngine(BASELINE, FAST)
        assert FaultKind.SPINE_FLEXION in kinds(run(engine, SUNK, 30))

    def test_a_tilted_torso_flags_spine_flexion(self):
        engine = RuleEngine(BASELINE, FAST)
        assert FaultKind.SPINE_FLEXION in kinds(
            run(engine, metrics(torso_angle=18.0), 30)
        )

    def test_head_tilt_flags_lateral_tilt(self):
        engine = RuleEngine(BASELINE, FAST)
        assert FaultKind.LATERAL_TILT in kinds(run(engine, metrics(eye_roll=14.0), 30))

    def test_uneven_shoulders_flag_lateral_tilt(self):
        engine = RuleEngine(BASELINE, FAST)
        assert FaultKind.LATERAL_TILT in kinds(
            run(engine, metrics(shoulder_roll=-13.0), 30)
        )

    def test_a_turned_head_flags_head_rotation(self):
        engine = RuleEngine(BASELINE, FAST)
        assert FaultKind.HEAD_ROTATION in kinds(run(engine, metrics(head_yaw=0.55), 30))

    def test_a_shrugged_gap_without_a_growing_face_flags_shoulder_shrug(self):
        """The gap closes exactly as forward head's does, but the face is not
        growing — so this is the shoulders lifting, not the head craning in."""
        engine = RuleEngine(BASELINE, FAST)
        faults = kinds(run(engine, metrics(head_shoulder_gap=0.333), 30))
        assert FaultKind.SHOULDER_SHRUG in faults
        assert FaultKind.FORWARD_HEAD not in faults

    def test_a_closing_gap_with_a_growing_face_is_forward_head_not_a_shrug(self):
        """Forward head already explains a closing gap once the face grows too —
        shoulder shrug must not also fire for the same evidence."""
        engine = RuleEngine(BASELINE, FAST)
        faults = kinds(run(engine, CRANING, 30))
        assert FaultKind.FORWARD_HEAD in faults
        assert FaultKind.SHOULDER_SHRUG not in faults


class TestSeverity:
    def test_worse_posture_scores_higher(self):
        mild = RuleEngine(BASELINE, FAST)
        severe = RuleEngine(BASELINE, FAST)
        mild_fault = run(mild, metrics(head_shoulder_gap=0.500, face_scale=0.330), 30)
        severe_fault = run(severe, metrics(head_shoulder_gap=0.200, face_scale=0.420), 30)
        assert severe_fault[0].severity > mild_fault[0].severity

    def test_severity_is_at_least_one_when_active(self):
        engine = RuleEngine(BASELINE, FAST)
        assert all(f.severity >= 1.0 for f in run(engine, CRANING, 30))


class TestGuidance:
    def test_every_fault_carries_a_cue_and_joints_to_highlight(self):
        engine = RuleEngine(BASELINE, FAST)
        faults = run(engine, metrics(head_shoulder_gap=0.333, face_scale=0.367, eye_roll=15.0), 30)
        assert len(faults) >= 2
        for fault in faults:
            assert fault.cue.strip()
            assert fault.joints

    def test_faults_come_back_most_severe_first(self):
        engine = RuleEngine(BASELINE, FAST)
        faults = run(
            engine,
            metrics(head_shoulder_gap=0.200, face_scale=0.420, eye_roll=9.5),
            30,
        )
        severities = [f.severity for f in faults]
        assert severities == sorted(severities, reverse=True)


class TestMissingData:
    def test_absent_torso_angle_does_not_crash_or_fire(self):
        engine = RuleEngine(BASELINE, FAST)
        faults = run(engine, metrics(torso_angle=None), 30)
        assert FaultKind.SPINE_FLEXION not in kinds(faults)

    def test_an_empty_frame_produces_nothing(self):
        engine = RuleEngine(BASELINE, FAST)
        assert run(engine, PostureMetrics(), 30) == []

    def test_losing_the_subject_clears_active_faults(self):
        """Walking away should not leave a fault latched on forever."""
        engine = RuleEngine(BASELINE, FAST)
        run(engine, CRANING, 5)
        assert engine.active
        run(engine, PostureMetrics(), 5)
        assert engine.active == frozenset()

    def test_a_baseline_missing_a_metric_skips_that_check(self):
        partial = baseline_from([PostureMetrics(screen_distance=0.09)])
        engine = RuleEngine(partial, FAST)
        assert FaultKind.FORWARD_HEAD not in kinds(run(engine, CRANING, 30))


class TestDrift:
    def test_no_drift_when_rolling_medians_match_baseline(self):
        assert evaluate_drift(BASELINE, GOOD.as_dict(), Thresholds()) is None

    def test_slow_sinking_is_reported_as_drift(self):
        sunk = {**GOOD.as_dict(), "shoulder_height": 0.690}
        fault = evaluate_drift(BASELINE, sunk, Thresholds())
        assert fault is not None and fault.kind == FaultKind.DRIFT

    def test_drift_needs_rolling_data(self):
        assert evaluate_drift(BASELINE, {}, Thresholds()) is None

    def test_drift_cue_mentions_recovering_posture(self):
        sunk = {**GOOD.as_dict(), "head_shoulder_gap": 0.520, "face_scale": 0.330}
        fault = evaluate_drift(BASELINE, sunk, Thresholds())
        assert fault is not None and fault.cue.strip()
