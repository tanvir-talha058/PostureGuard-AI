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
import time
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger(__name__)


#: A read can fail transiently — a laptop lid, a moment of USB contention, another app
#: grabbing the device briefly. Only a sustained run of failures means the camera is
#: actually gone.
HEALTH_GRACE_SECONDS = 2.0
#: How often to attempt reopening a device that has dropped out.
RECONNECT_INTERVAL_SECONDS = 3.0
#: How many indices to probe when the platform cannot enumerate devices by name.
MAX_PROBE_INDEX = 5


class CameraError(RuntimeError):
    """The webcam could not be opened or produced no frames."""


@dataclass(frozen=True)
class CameraInfo:
    index: int
    name: str

    def __str__(self) -> str:
        return self.name


def available_cameras() -> list[CameraInfo]:
    """The cameras actually attached to this machine.

    Qt enumerates devices by name without opening them, which is both faster and far
    more useful than "Camera 0" — a user with a laptop webcam and an external one needs
    to be told which is which.

    Caveat worth knowing: Qt's ordering and OpenCV's device indices are not guaranteed
    to agree. On Windows with the DirectShow backend they do in practice, and the
    alternative is offering no names at all. If a selection ever opens the wrong device,
    this mapping is the first thing to suspect.
    """
    try:
        from PySide6.QtMultimedia import QMediaDevices

        inputs = QMediaDevices.videoInputs()
        if inputs:
            return [
                CameraInfo(index, device.description() or f"Camera {index}")
                for index, device in enumerate(inputs)
            ]
    except Exception:
        log.debug("Qt device enumeration unavailable; probing indices instead")

    # Fallback: actually open each index and see what answers. Slow, so it is only
    # reached when Qt cannot tell us.
    backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
    found: list[CameraInfo] = []
    for index in range(MAX_PROBE_INDEX):
        probe = cv2.VideoCapture(index, backend)
        opened = probe.isOpened()
        probe.release()
        if opened:
            found.append(CameraInfo(index, f"Camera {index}"))
    return found


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
        self._healthy = True
        self._failing_since: float | None = None
        self._last_reconnect = 0.0
        self._paused = threading.Event()

    def start(self) -> Camera:
        if self._thread is not None:
            return self

        # _open_device uses CAP_DSHOW first, which avoids the multi-second MSMF
        # initialisation stall on Windows, and asks the driver for a shallow buffer.
        capture = self._open_device()
        if capture is None:
            raise CameraError(
                f"Could not open camera {self.config.index}. "
                "Check that no other app is using it and that camera access is allowed."
            )
        self._capture = capture
        self._healthy = True
        self._failing_since = None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()
        return self

    def _open_device(self) -> cv2.VideoCapture | None:
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
        capture = cv2.VideoCapture(self.config.index, backend)
        if not capture.isOpened():
            capture.release()
            capture = cv2.VideoCapture(self.config.index)
        if not capture.isOpened():
            capture.release()
            return None
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.config.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.height)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return capture

    def _run(self) -> None:
        was_paused = False
        while not self._stop.is_set():
            if self._paused.is_set():
                if not was_paused:
                    # Release from inside this thread only — the main thread never
                    # touches `_capture` directly, so there is no handle shared
                    # between two threads mid-release to race on.
                    if self._capture is not None:
                        self._capture.release()
                        self._capture = None
                    with self._lock:
                        self._frame = None
                        # Pausing is not a failure; a stale timer must not survive
                        # into the next resume and immediately look sustained.
                        self._failing_since = None
                    was_paused = True
                self._stop.wait(0.2)
                continue
            was_paused = False

            if self._capture is None:
                # Either just resumed, or the device dropped out mid-stream. Keep
                # trying to get it back — unplugging and replugging a webcam should
                # recover on its own, not require a restart.
                if time.monotonic() - self._last_reconnect < RECONNECT_INTERVAL_SECONDS:
                    self._stop.wait(0.2)
                    continue
                self._last_reconnect = time.monotonic()
                self._capture = self._open_device()
                if self._capture is None:
                    # A device that will not even open is exactly as lost as one that
                    # stops mid-stream, and must count toward the same grace period —
                    # otherwise a camera unplugged while paused is never reported lost
                    # once the user returns, because no read ever gets the chance to fail.
                    self._on_read_failure()
                    continue
                log.info("Camera %s opened", self.config.index)

            ok, frame = self._capture.read()
            if not ok:
                self._on_read_failure()
                continue

            if self.config.mirror:
                frame = cv2.flip(frame, 1)
            with self._lock:
                self._frame = frame
                self._frames_read += 1
                self._healthy = True
                self._failing_since = None

    def _on_read_failure(self) -> None:
        """A failed read: transient at first, a lost camera if it persists."""
        now = time.monotonic()
        with self._lock:
            if self._failing_since is None:
                self._failing_since = now
            sustained = now - self._failing_since >= HEALTH_GRACE_SECONDS
            if sustained and self._healthy:
                self._healthy = False
                log.warning("Camera %s stopped delivering frames", self.config.index)
            if not self._healthy:
                # Drop the stale frame. Continuing to serve the last good image would
                # show a frozen picture with a skeleton drawn on it — indistinguishable
                # from live, and the app would look like it was still watching.
                self._frame = None

        if not self.healthy and self._capture is not None:
            # Release and let the reconnect path try again from scratch; a capture
            # handle to a removed device never recovers on its own.
            self._capture.release()
            self._capture = None
        self._stop.wait(0.05)

    def pause(self) -> None:
        """Release the device: stops drawing power and turns off the capture LED.

        A lit camera light while the app claims to be paused reads as "still watching
        you" — that would cost the whole product's privacy promise for the sake of a
        faster resume, which is not a trade worth making. The reader thread performs
        the actual release, so pausing from the main thread never touches the capture
        handle directly while the reader might be mid-read on it.

        Distinct from a lost camera: pausing is intentional and must never flip
        `healthy` to False, trigger a reconnect-failure warning, or dim anyone's
        screen for a posture that has stopped being observed on purpose.
        """
        self._paused.set()

    def resume(self) -> None:
        if not self._paused.is_set():
            return
        self._paused.clear()
        # Try to reopen immediately rather than waiting out a full reconnect interval
        # that was ticking while nothing needed reconnecting.
        self._last_reconnect = 0.0

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    def read(self) -> np.ndarray | None:
        """The most recent frame, or None if none has arrived yet."""
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    @property
    def frames_read(self) -> int:
        with self._lock:
            return self._frames_read

    @property
    def healthy(self) -> bool:
        """False once the device has stopped delivering frames for long enough.

        The distinction matters: without it, a dead camera and an empty chair look
        identical to the rest of the app, and the user is told "no subject" while the
        truth is that nothing is being watched at all.
        """
        with self._lock:
            return self._healthy

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

    def __enter__(self) -> Camera:
        return self.start()

    def __exit__(self, *exc_info: object) -> None:
        self.stop()
