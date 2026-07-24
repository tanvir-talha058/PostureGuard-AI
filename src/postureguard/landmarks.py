"""Pose landmark data model.

Deliberately free of MediaPipe, OpenCV and Qt imports so the pure metric and rule
layers — and their tests — can work with fixture landmark sets and never touch a camera.

Coordinates are normalized to the frame: ``x`` in [0, 1] across the width, ``y`` in
[0, 1] down the height. Note that this makes x and y *differently scaled* on a
non-square frame; anything measuring a distance or an angle must correct for aspect
ratio first (see :func:`postureguard.metrics.to_square_units`).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

# Landmarks we care about, mapped to their MediaPipe Pose index. "left" and "right"
# are the subject's own, not the viewer's — so on an unmirrored frame the subject's
# left appears on the right of the image.
JOINT_INDICES: dict[str, int] = {
    "nose": 0,
    "left_eye": 2,
    "right_eye": 5,
    "left_ear": 7,
    "right_ear": 8,
    "left_shoulder": 11,
    "right_shoulder": 12,
    "left_hip": 23,
    "right_hip": 24,
}

# Below this, MediaPipe is guessing at an occluded joint. Desks routinely hide hips,
# so metrics that depend on them must degrade rather than consume the guess.
MIN_VISIBILITY = 0.5


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    z: float = 0.0
    visibility: float = 1.0


@dataclass(frozen=True)
class Landmarks:
    """A single frame's detected joints."""

    points: Mapping[str, Point]

    def get(self, name: str, min_visibility: float = MIN_VISIBILITY) -> Point | None:
        """Return the joint, or None if absent or too occluded to trust."""
        point = self.points.get(name)
        if point is None or point.visibility < min_visibility:
            return None
        return point

    def visible(self, *names: str, min_visibility: float = MIN_VISIBILITY) -> bool:
        """True only if every named joint is present and trustworthy."""
        return all(self.get(name, min_visibility) is not None for name in names)
