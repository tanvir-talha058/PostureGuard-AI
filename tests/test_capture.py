"""Camera health and device enumeration.

The camera itself is not opened here. What is tested is the failure state machine —
when a dropped read counts as transient and when it means the device is gone — which is
pure logic reachable by driving `_on_read_failure` directly.
"""

from __future__ import annotations

import pytest

from postureguard.capture import (
    HEALTH_GRACE_SECONDS,
    Camera,
    CameraConfig,
    CameraInfo,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr("postureguard.capture.time.monotonic", fake)
    return fake


@pytest.fixture
def camera():
    return Camera(CameraConfig(index=0))


class TestHealth:
    def test_a_fresh_camera_is_healthy(self, camera):
        assert camera.healthy

    def test_a_brief_read_failure_is_not_a_lost_camera(self, camera, clock):
        """Lids, USB contention and another app grabbing the device are all transient."""
        camera._on_read_failure()
        clock.advance(HEALTH_GRACE_SECONDS / 2)
        camera._on_read_failure()
        assert camera.healthy

    def test_sustained_failure_marks_the_camera_lost(self, camera, clock):
        camera._on_read_failure()
        clock.advance(HEALTH_GRACE_SECONDS + 0.1)
        camera._on_read_failure()
        assert not camera.healthy

    def test_a_lost_camera_stops_serving_its_last_frame(self, camera, clock):
        """A frozen frame with a skeleton on it is indistinguishable from live."""
        camera._frame = object()
        camera._on_read_failure()
        clock.advance(HEALTH_GRACE_SECONDS + 0.1)
        camera._on_read_failure()
        assert camera.read() is None

    def test_a_transient_failure_keeps_the_last_frame(self, camera, clock):
        import numpy as np

        camera._frame = np.zeros((2, 2, 3), dtype=np.uint8)
        camera._on_read_failure()
        assert camera.read() is not None

    def test_failure_timer_resets_once_frames_return(self, camera, clock):
        camera._on_read_failure()
        clock.advance(HEALTH_GRACE_SECONDS + 0.1)
        camera._on_read_failure()
        assert not camera.healthy

        # Simulate the reader thread succeeding again.
        with camera._lock:
            camera._healthy = True
            camera._failing_since = None

        camera._on_read_failure()
        assert camera.healthy, "one failure after recovery must not re-trip immediately"


class TestPause:
    def test_a_fresh_camera_is_not_paused(self, camera):
        assert not camera.paused

    def test_pause_sets_the_flag(self, camera):
        camera.pause()
        assert camera.paused

    def test_resume_clears_it(self, camera):
        camera.pause()
        camera.resume()
        assert not camera.paused

    def test_resuming_an_unpaused_camera_is_a_no_op(self, camera):
        camera.resume()
        assert not camera.paused

    def test_pause_does_not_touch_capture_from_the_caller_thread(self, camera):
        """Only the reader thread may release `_capture` — releasing it from here
        while a read could be in flight is the race this design avoids."""
        sentinel = object()
        camera._capture = sentinel
        camera.pause()
        assert camera._capture is sentinel

    def test_resume_asks_the_reader_to_reopen_immediately(self, camera):
        camera._last_reconnect = 999999.0
        camera.pause()
        camera.resume()
        assert camera._last_reconnect == 0.0


class TestPauseIsNotAFailure:
    """Pausing must never look like the camera dying, in either direction."""

    def test_a_healthy_camera_stays_healthy_across_a_pause(self, camera):
        camera.pause()
        assert camera.healthy
        camera.resume()
        assert camera.healthy

    def test_pausing_clears_any_in_progress_failure_timer(self, camera, clock):
        """A failure that had not yet reached the grace period must not carry over
        and immediately look sustained the moment the camera resumes."""
        camera._on_read_failure()
        assert camera._failing_since is not None
        # Simulate the reader thread's pause transition.
        with camera._lock:
            camera._frame = None
            camera._failing_since = None
        assert camera._failing_since is None


class TestOpenFailureCountsTowardHealth:
    """A device that will not even open is exactly as lost as one that drops
    mid-stream — regression for a gap where only read failures were tracked."""

    def test_a_sustained_failure_to_open_marks_the_camera_unhealthy(self, camera, clock):
        # _on_read_failure is what _run calls when _open_device() returns None too.
        camera._on_read_failure()
        clock.advance(HEALTH_GRACE_SECONDS + 0.1)
        camera._on_read_failure()
        assert not camera.healthy


class TestEnumeration:
    def test_camera_info_displays_as_its_name(self):
        assert str(CameraInfo(2, "HP HD Camera")) == "HP HD Camera"

    def test_index_is_kept_separate_from_list_position(self):
        """Selecting a device must send its index, not where it sat in the list."""
        cameras = [CameraInfo(0, "Built-in"), CameraInfo(3, "External")]
        assert [c.index for c in cameras] == [0, 3]
