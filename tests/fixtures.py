"""Synthetic landmark builders.

These stand in for a webcam so the pure layers can be tested deterministically.
Poses are described in *square units* (the aspect-corrected space metrics work in)
and converted back to normalized frame coordinates on the way out, which is the same
round trip the real pipeline performs.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from postureguard.landmarks import Landmarks, Point

ASPECT = 16 / 9
CENTER = 0.5 * ASPECT


@dataclass
class Pose:
    """A seated subject, described by the few dimensions the metrics actually read."""

    shoulder_width: float = 0.30
    head_shoulder_gap: float = 0.20
    inter_ocular: float = 0.09
    shoulder_y: float = 0.62
    hip_y: float = 0.95
    center_x: float = CENTER
    hip_offset_x: float = 0.0
    eye_tilt_deg: float = 0.0
    shoulder_tilt_deg: float = 0.0
    hip_visibility: float = 1.0

    def scaled(self, factor: float) -> Pose:
        """The same posture, further from or closer to the camera.

        Every length shrinks together and no ratio changes — which is exactly the
        case forward-head detection must not mistake for craning.
        """
        return Pose(
            shoulder_width=self.shoulder_width * factor,
            head_shoulder_gap=self.head_shoulder_gap * factor,
            inter_ocular=self.inter_ocular * factor,
            shoulder_y=self.shoulder_y,
            hip_y=self.hip_y,
            center_x=self.center_x,
            hip_offset_x=self.hip_offset_x * factor,
            eye_tilt_deg=self.eye_tilt_deg,
            shoulder_tilt_deg=self.shoulder_tilt_deg,
            hip_visibility=self.hip_visibility,
        )


def _pair(cx: float, cy: float, half_width: float, tilt_deg: float):
    """Two symmetric points about (cx, cy), rotated by tilt_deg."""
    rad = math.radians(tilt_deg)
    dx = half_width * math.cos(rad)
    dy = half_width * math.sin(rad)
    return (cx - dx, cy - dy), (cx + dx, cy + dy)


def build(pose: Pose = Pose()) -> Landmarks:
    """Render a Pose into Landmarks in normalized frame coordinates."""
    ear_y = pose.shoulder_y - pose.head_shoulder_gap
    eye_y = ear_y + 0.01

    right_sh, left_sh = _pair(
        pose.center_x, pose.shoulder_y, pose.shoulder_width / 2, pose.shoulder_tilt_deg
    )
    right_eye, left_eye = _pair(
        pose.center_x, eye_y, pose.inter_ocular / 2, pose.eye_tilt_deg
    )
    right_ear, left_ear = _pair(pose.center_x, ear_y, pose.shoulder_width * 0.23, 0.0)
    right_hip, left_hip = _pair(
        pose.center_x + pose.hip_offset_x, pose.hip_y, pose.shoulder_width * 0.4, 0.0
    )

    def pt(xy, visibility: float = 1.0) -> Point:
        # Back out of square units into normalized frame coordinates.
        return Point(x=xy[0] / ASPECT, y=xy[1], visibility=visibility)

    return Landmarks(
        {
            "nose": pt((pose.center_x, eye_y + 0.03)),
            "right_eye": pt(right_eye),
            "left_eye": pt(left_eye),
            "right_ear": pt(right_ear),
            "left_ear": pt(left_ear),
            "right_shoulder": pt(right_sh),
            "left_shoulder": pt(left_sh),
            "right_hip": pt(right_hip, pose.hip_visibility),
            "left_hip": pt(left_hip, pose.hip_visibility),
        }
    )


UPRIGHT = Pose()

# Head craned forward and down: the gap closes, the face grows.
SLUMPED = Pose(head_shoulder_gap=0.10, inter_ocular=0.11)

# Same posture, chair pushed back. Absolute sizes drop, ratios hold.
FURTHER_AWAY = UPRIGHT.scaled(0.8)
