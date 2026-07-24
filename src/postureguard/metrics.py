"""Landmarks to posture metrics.

Pure functions — no camera, no UI, no state. Everything here is derived from a single
frame's landmarks, which makes the whole module testable against synthetic poses.

**Why these metrics and not the clinical ones.** A desk webcam looks at you head-on.
Forward-head posture is translation *toward* the lens, so the side-view craniovertebral
angle simply is not observable. What is observable from the front is that craning drops
the ears toward the shoulder line while enlarging the face. Neither signal identifies
forward head alone — pushing your chair back also enlarges the face — so both are
expressed as ratios against shoulder width, which cancels distance out. Whatever
survives that normalization is genuine posture change.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields

from .landmarks import Landmarks, Point

# Below this many square units, the subject is effectively a point and every ratio
# blows up. Happens on bad detections, not on real people.
_MIN_SHOULDER_WIDTH = 1e-3


@dataclass(frozen=True)
class PostureMetrics:
    """One frame's posture, distance-normalized where possible.

    Every field is optional: joints get occluded, subjects leave the frame, and a
    missing metric must stay missing rather than become a plausible-looking zero.
    """

    #: (shoulder_mid_y - ear_mid_y) / shoulder_width. Falls as the head cranes down.
    head_shoulder_gap: float | None = None
    #: inter-ocular distance / shoulder width. Rises as the head translates forward.
    face_scale: float | None = None
    #: inter-ocular distance in frame units. Rises as the whole body leans in.
    screen_distance: float | None = None
    #: shoulder line angle from horizontal, degrees. Positive = subject's left lower.
    shoulder_roll: float | None = None
    #: eye line angle from horizontal, degrees. Positive = subject's left eye lower.
    eye_roll: float | None = None
    #: shoulder-to-hip vector angle from vertical, degrees. None when hips are hidden.
    torso_angle: float | None = None
    #: shoulder midpoint height in frame units, y measured downward. Rises as the
    #: subject sinks. Unlike the ratios this one is not distance-normalized, so it is
    #: only meaningful against a baseline captured from the same camera position.
    shoulder_height: float | None = None

    def any_available(self) -> bool:
        return any(getattr(self, f.name) is not None for f in fields(self))

    def as_dict(self) -> dict[str, float | None]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


#: Human names for the metrics, for anywhere a user reads them. Field names are for
#: code; "head_shoulder_gap" in an interface is the implementation leaking out.
METRIC_LABELS: dict[str, str] = {
    "head_shoulder_gap": "head position",
    "face_scale": "head distance",
    "screen_distance": "screen distance",
    "shoulder_roll": "shoulder line",
    "eye_roll": "head tilt",
    "torso_angle": "torso lean",
    "shoulder_height": "seated height",
}


def describe(names) -> str:
    """A readable list of metric names, in the order they are defined above."""
    ordered = [METRIC_LABELS[n] for n in METRIC_LABELS if n in set(names)]
    if not ordered:
        return "nothing yet"
    if len(ordered) == 1:
        return ordered[0]
    return ", ".join(ordered[:-1]) + f" and {ordered[-1]}"


@dataclass(frozen=True)
class _Vec:
    x: float
    y: float


def to_square_units(point: Point, aspect: float) -> _Vec:
    """Normalized frame coordinates carry different scales on x and y.

    On a 16:9 frame, one unit of x spans 1.78x the physical distance of one unit of y.
    Measuring a length or an angle without correcting for that is wrong by up to 60
    degrees at a 45 degree tilt. Scaling x by the aspect ratio puts both axes in the
    same units (frame heights), after which ordinary trigonometry applies.
    """
    return _Vec(point.x * aspect, point.y)


def _midpoint(*points: Point | None, aspect: float) -> _Vec | None:
    """Average whichever of the given joints are actually visible.

    One ear is enough to locate the head; requiring both would drop the metric every
    time the subject turns slightly.
    """
    present = [to_square_units(p, aspect) for p in points if p is not None]
    if not present:
        return None
    return _Vec(
        sum(v.x for v in present) / len(present),
        sum(v.y for v in present) / len(present),
    )


def _distance(a: _Vec, b: _Vec) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _angle_from_horizontal(start: _Vec, end: _Vec) -> float:
    """Degrees of the start-to-end vector away from horizontal, y measured downward."""
    return math.degrees(math.atan2(end.y - start.y, end.x - start.x))


def _angle_from_vertical(top: _Vec, bottom: _Vec) -> float:
    """Degrees of the top-to-bottom vector away from straight down."""
    return math.degrees(math.atan2(bottom.x - top.x, bottom.y - top.y))


def compute_metrics(landmarks: Landmarks, aspect: float) -> PostureMetrics:
    """Derive posture metrics from one frame.

    Args:
        landmarks: detected joints in normalized frame coordinates.
        aspect: frame width divided by height, used to square up the coordinate space.
    """
    get = landmarks.get

    left_shoulder, right_shoulder = get("left_shoulder"), get("right_shoulder")
    left_eye, right_eye = get("left_eye"), get("right_eye")

    eye_mid = _midpoint(left_eye, right_eye, aspect=aspect)
    ear_mid = _midpoint(get("left_ear"), get("right_ear"), aspect=aspect)
    # Ears are the better head reference, but they occlude easily on a turned head;
    # the eyes are a serviceable fallback for the vertical gap.
    head_mid = ear_mid or eye_mid

    # Absolute, so it tracks how close the subject is rather than how they are sitting.
    screen_distance = None
    if left_eye is not None and right_eye is not None:
        screen_distance = _distance(
            to_square_units(left_eye, aspect), to_square_units(right_eye, aspect)
        )

    eye_roll = None
    if left_eye is not None and right_eye is not None:
        eye_roll = _angle_from_horizontal(
            to_square_units(right_eye, aspect), to_square_units(left_eye, aspect)
        )

    if left_shoulder is None or right_shoulder is None:
        # Shoulder width is the yardstick every ratio is measured against. Without it
        # only the absolute metrics survive.
        return PostureMetrics(
            screen_distance=screen_distance,
            eye_roll=eye_roll,
        )

    left_sh = to_square_units(left_shoulder, aspect)
    right_sh = to_square_units(right_shoulder, aspect)
    shoulder_width = _distance(left_sh, right_sh)
    shoulder_roll = _angle_from_horizontal(right_sh, left_sh)
    shoulder_mid = _Vec((left_sh.x + right_sh.x) / 2, (left_sh.y + right_sh.y) / 2)

    if shoulder_width < _MIN_SHOULDER_WIDTH:
        return PostureMetrics(
            screen_distance=screen_distance,
            eye_roll=eye_roll,
            shoulder_roll=shoulder_roll,
            shoulder_height=shoulder_mid.y,
        )

    head_shoulder_gap = None
    if head_mid is not None:
        head_shoulder_gap = (shoulder_mid.y - head_mid.y) / shoulder_width

    face_scale = None
    if screen_distance is not None:
        face_scale = screen_distance / shoulder_width

    torso_angle = None
    hip_mid = _midpoint(get("left_hip"), get("right_hip"), aspect=aspect)
    if hip_mid is not None:
        # Desks hide hips constantly. When they are hidden the metric is absent, not
        # zero — the rules layer skips spine flexion rather than trusting a guess.
        torso_angle = _angle_from_vertical(shoulder_mid, hip_mid)

    return PostureMetrics(
        head_shoulder_gap=head_shoulder_gap,
        face_scale=face_scale,
        screen_distance=screen_distance,
        shoulder_roll=shoulder_roll,
        eye_roll=eye_roll,
        torso_angle=torso_angle,
        shoulder_height=shoulder_mid.y,
    )
