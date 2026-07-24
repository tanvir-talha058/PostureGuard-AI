"""MediaPipe Pose wrapper and landmark smoothing.

Converts BGR frames into the plain :class:`Landmarks` structure the rest of the app
speaks, so MediaPipe stays contained in this one module.

The model is downloaded on first run rather than vendored — it is ~6 MB and does not
belong in git. It is cached under the user's data directory afterwards.
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions
from mediapipe.tasks.python.vision import (
    PoseLandmarker,
    PoseLandmarkerOptions,
    RunningMode,
)

from .landmarks import JOINT_INDICES, Landmarks, Point
from .paths import model_dir

log = logging.getLogger(__name__)

MODEL_NAME = "pose_landmarker_lite.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
    "pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
)


class ModelUnavailable(RuntimeError):
    """The pose model is neither cached nor downloadable."""


def ensure_model(destination: Path | None = None) -> Path:
    """Return the local model path, downloading it once if needed."""
    path = destination or (model_dir() / MODEL_NAME)
    if path.exists() and path.stat().st_size > 0:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Downloading pose model (~6 MB) to %s", path)
    # Download to a temporary name first so an interrupted download can never leave a
    # truncated file that looks valid on the next run.
    partial = path.with_suffix(path.suffix + ".part")
    try:
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            partial.write_bytes(response.read())
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        partial.unlink(missing_ok=True)
        raise ModelUnavailable(
            f"Could not download the pose model from {MODEL_URL}: {exc}"
        ) from exc
    partial.replace(path)
    return path


class LandmarkSmoother:
    """Exponentially weighted smoothing of landmark positions.

    Raw pose output jitters by a pixel or two every frame. Left alone that noise
    propagates into every ratio and makes the metric readout unreadable, so positions
    are smoothed before any measurement is taken.

    Visibility is smoothed too, which stops joints from strobing in and out of the
    "trustworthy" band right at the visibility threshold.
    """

    def __init__(self, alpha: float = 0.4) -> None:
        #: Weight of the newest frame. Lower is steadier but laggier.
        self.alpha = alpha
        self._previous: dict[str, Point] = {}

    def apply(self, landmarks: Landmarks) -> Landmarks:
        smoothed: dict[str, Point] = {}
        for name, point in landmarks.points.items():
            previous = self._previous.get(name)
            if previous is None:
                smoothed[name] = point
            else:
                a = self.alpha
                smoothed[name] = Point(
                    x=a * point.x + (1 - a) * previous.x,
                    y=a * point.y + (1 - a) * previous.y,
                    z=a * point.z + (1 - a) * previous.z,
                    visibility=a * point.visibility + (1 - a) * previous.visibility,
                )
        self._previous = smoothed
        return Landmarks(smoothed)

    def reset(self) -> None:
        self._previous = {}


class PoseTracker:
    """Detects a single seated subject in a stream of frames."""

    def __init__(self, model_path: Path | None = None, smoothing: float = 0.4) -> None:
        path = model_path or ensure_model()
        options = PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(path)),
            # VIDEO mode lets MediaPipe use temporal context between frames, which is
            # both steadier and cheaper than treating each frame as a fresh image.
            running_mode=RunningMode.VIDEO,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = PoseLandmarker.create_from_options(options)
        self._smoother = LandmarkSmoother(smoothing)
        self._last_timestamp_ms = -1

    def detect(self, frame: np.ndarray, timestamp_ms: int) -> Landmarks | None:
        """Locate the subject in one frame. Returns None when nobody is visible."""
        # MediaPipe's VIDEO mode requires strictly increasing timestamps and raises
        # if one repeats — easy to hit when the UI timer outruns the camera.
        if timestamp_ms <= self._last_timestamp_ms:
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, timestamp_ms)

        if not result.pose_landmarks:
            self._smoother.reset()
            return None

        detected = result.pose_landmarks[0]
        points: dict[str, Point] = {}
        for name, index in JOINT_INDICES.items():
            if index >= len(detected):
                continue
            landmark = detected[index]
            points[name] = Point(
                x=landmark.x,
                y=landmark.y,
                z=getattr(landmark, "z", 0.0),
                visibility=getattr(landmark, "visibility", 1.0),
            )
        return self._smoother.apply(Landmarks(points))

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self) -> "PoseTracker":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
