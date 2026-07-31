import math

import pytest
from fixtures import ASPECT, FURTHER_AWAY, SLUMPED, UPRIGHT, Pose, build

from postureguard.landmarks import Landmarks, Point
from postureguard.metrics import compute_metrics


def m(pose: Pose):
    return compute_metrics(build(pose), aspect=ASPECT)


class TestUpright:
    def test_ratios_match_the_constructed_pose(self):
        metrics = m(UPRIGHT)
        assert metrics.head_shoulder_gap == pytest.approx(0.20 / 0.30, rel=1e-6)
        assert metrics.face_scale == pytest.approx(0.09 / 0.30, rel=1e-6)
        assert metrics.screen_distance == pytest.approx(0.09, rel=1e-6)

    def test_a_level_subject_has_no_roll(self):
        metrics = m(UPRIGHT)
        assert metrics.shoulder_roll == pytest.approx(0.0, abs=1e-6)
        assert metrics.eye_roll == pytest.approx(0.0, abs=1e-6)

    def test_a_vertical_torso_reads_zero(self):
        assert m(UPRIGHT).torso_angle == pytest.approx(0.0, abs=1e-6)


class TestForwardHead:
    def test_craning_closes_the_gap_and_grows_the_face(self):
        upright, slumped = m(UPRIGHT), m(SLUMPED)
        assert slumped.head_shoulder_gap < upright.head_shoulder_gap
        assert slumped.face_scale > upright.face_scale

    def test_moving_away_leaves_both_ratios_untouched(self):
        """The disambiguation that stops chair movement reading as posture change."""
        upright, away = m(UPRIGHT), m(FURTHER_AWAY)
        assert away.head_shoulder_gap == pytest.approx(upright.head_shoulder_gap, rel=1e-6)
        assert away.face_scale == pytest.approx(upright.face_scale, rel=1e-6)

    def test_moving_away_does_shrink_absolute_screen_distance(self):
        assert m(FURTHER_AWAY).screen_distance < m(UPRIGHT).screen_distance


class TestTilt:
    def test_head_tilt_shows_up_as_eye_roll(self):
        assert m(Pose(eye_tilt_deg=12.0)).eye_roll == pytest.approx(12.0, abs=0.5)

    def test_uneven_shoulders_show_up_as_shoulder_roll(self):
        assert m(Pose(shoulder_tilt_deg=-8.0)).shoulder_roll == pytest.approx(-8.0, abs=0.5)

    def test_tilt_is_measured_in_square_units_not_raw_normalized(self):
        """A 45 degree tilt must read as 45, not as atan(aspect * tan(45))."""
        tilted = m(Pose(eye_tilt_deg=45.0))
        assert tilted.eye_roll == pytest.approx(45.0, abs=0.5)
        naive = math.degrees(math.atan(ASPECT * math.tan(math.radians(45.0))))
        assert naive == pytest.approx(60.6, abs=0.5)  # what skipping the fix would give


class TestSpineFlexion:
    def test_leaning_sideways_tilts_the_torso_vector(self):
        assert m(Pose(hip_offset_x=0.10)).torso_angle == pytest.approx(
            math.degrees(math.atan2(0.10, 0.33)), abs=0.5
        )

    def test_sinking_in_the_chair_raises_shoulder_height(self):
        """y grows downward, so a collapsing torso reads as a larger value."""
        assert m(Pose(shoulder_y=0.70)).shoulder_height > m(UPRIGHT).shoulder_height

    def test_shoulder_height_tracks_the_shoulder_midpoint(self):
        assert m(UPRIGHT).shoulder_height == pytest.approx(0.62, abs=1e-6)


class TestDegradation:
    def test_occluded_hips_yield_no_torso_angle(self):
        assert m(Pose(hip_visibility=0.2)).torso_angle is None

    def test_occluded_hips_do_not_disturb_the_other_metrics(self):
        occluded = m(Pose(hip_visibility=0.2))
        assert occluded.head_shoulder_gap == pytest.approx(m(UPRIGHT).head_shoulder_gap)
        assert occluded.face_scale == pytest.approx(m(UPRIGHT).face_scale)

    def test_missing_shoulders_yield_no_ratio_metrics(self):
        no_shoulders = Landmarks(
            {k: v for k, v in build(UPRIGHT).points.items() if "shoulder" not in k}
        )
        metrics = compute_metrics(no_shoulders, aspect=ASPECT)
        assert metrics.head_shoulder_gap is None
        assert metrics.face_scale is None
        assert metrics.torso_angle is None

    def test_eyes_alone_still_give_screen_distance(self):
        eyes_only = Landmarks(
            {k: v for k, v in build(UPRIGHT).points.items() if "eye" in k}
        )
        assert compute_metrics(eyes_only, aspect=ASPECT).screen_distance is not None

    def test_a_degenerate_zero_width_subject_does_not_divide_by_zero(self):
        collapsed = Landmarks(
            {
                "left_shoulder": Point(0.5, 0.62),
                "right_shoulder": Point(0.5, 0.62),
                "left_ear": Point(0.5, 0.42),
                "right_ear": Point(0.5, 0.42),
                "left_eye": Point(0.5, 0.43),
                "right_eye": Point(0.5, 0.43),
            }
        )
        metrics = compute_metrics(collapsed, aspect=ASPECT)
        assert metrics.head_shoulder_gap is None
        assert metrics.face_scale is None

    def test_an_empty_frame_produces_all_none(self):
        metrics = compute_metrics(Landmarks({}), aspect=ASPECT)
        assert not metrics.any_available()


class TestHeadYaw:
    def test_facing_the_camera_reads_near_zero(self):
        assert m(UPRIGHT).head_yaw == pytest.approx(0.0, abs=1e-6)

    def test_turning_the_head_shifts_the_nose_off_the_eye_midline(self):
        points = dict(build(UPRIGHT).points)
        nose = points["nose"]
        points["nose"] = Point(nose.x + 0.02, nose.y, visibility=nose.visibility)
        metrics = compute_metrics(Landmarks(points), aspect=ASPECT)
        assert metrics.head_yaw > 0

    def test_missing_nose_yields_no_yaw(self):
        points = {k: v for k, v in build(UPRIGHT).points.items() if k != "nose"}
        assert compute_metrics(Landmarks(points), aspect=ASPECT).head_yaw is None


class TestSingleSided:
    def test_one_visible_ear_is_enough_for_the_gap(self):
        points = dict(build(UPRIGHT).points)
        points["left_ear"] = Point(
            points["left_ear"].x, points["left_ear"].y, visibility=0.1
        )
        metrics = compute_metrics(Landmarks(points), aspect=ASPECT)
        assert metrics.head_shoulder_gap is not None
