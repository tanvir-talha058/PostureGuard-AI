"""Threaded webcam capture.

The camera produces frames whether or not anything is consuming them, and OpenCV
buffers what you don't read. Pull frames on the UI timer and you end up processing a
queue that grows all day — the skeleton lags further behind the user the longer the app
runs, which is fatal for a tool whose whole value is immediacy.

So a background thread reads continuously and keeps only the newest frame. Consumers
sample it whenever they like and always get the present, never a backlog.

No frame is ever written to disk. Frames live in memory and are overwritten.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)


class CameraError(RuntimeError):
    """The webcam could not be opened or produced no frames."""


@dataclass
class CameraConfig:
    index: int = 0
    width: int = 640
    height: int = 480
    #: Mirror the image so the overlay behaves like a mirror and self-correction is
    #: intuitive. Note this swaps MediaPipe's anatomical labels: on a mirrored frame
    #: "left_shoulder" is the subject's right. Harmless here — every metric is either
    #: side-symmetric or compared as a magnitude against a baseline captured in the
    #: same mirrored space.
    mirror: bool = True


class Camera:
    """Latest-frame-wins webcam reader."""

    def __init__(self, config: CameraConfig | None = None) -> None:
        self.config = config or CameraConfig()
        self._capture: cv2.VideoCapture | None = None
        self._frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frames_read = 0

    def start(self) -> "Camera":
        if self._thread is not None:
            return self

        # CAP_DSHOW avoids the multi-second MSMF initialisation stall on Windows.
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
        capture = cv2.VideoCapture(self.config.index, backend)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(self.config.index)
        if not capture.isOpened():
            raise CameraError(
                f"Could not open camera {self.config.index}. "
                "Check that no other app is using it and that camera access is allowed."
            )

        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        # Ask the driver for a shallow buffer too; not all backends honour it, which
        # is why the reader thread exists regardless.
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self._capture = capture
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()
        return self

    def _run(self) -> None:
        assert self._capture is not None
        while not self._stop.is_set():
            ok, frame = self._capture.read()
            if not ok:
                # A transient read failure is common when a laptop lid closes or the
                # device is briefly grabbed elsewhere. Keep trying rather than dying.
                self._stop.wait(0.05)
                continue
            if self.config.mirror:
                frame = cv2.flip(frame, 1)
            with self._lock:
                self._frame = frame
                self._frames_read += 1

    def read(self) -> np.ndarray | None:
        """The most recent frame, or None if none has arrived yet."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    @property
    def frames_read(self) -> int:
        with self._lock:
            return self._frames_read

    @property
    def aspect(self) -> float:
        """Frame width over height. Metrics need this to square up the coordinates."""
        with self._lock:
            frame = self._frame
        if frame is None:
            return self.config.width / self.config.height
        height, width = frame.shape[:2]
        return width / height

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        with self._lock:
            self._frame = None

    def __enter__(self) -> "Camera":
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()
