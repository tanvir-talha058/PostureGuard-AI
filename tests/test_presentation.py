"""Fullscreen-foreground-window detection.

Mirrors test_power.py's approach: the public function is tested by monkeypatching the
private single-purpose calls it wraps, so the suite runs the same on any platform
without a real fullscreen window to check against.
"""

from __future__ import annotations

from postureguard import presentation


class TestForegroundIsFullscreen:
    def test_true_when_the_window_exactly_covers_its_monitor(self, monkeypatch):
        monkeypatch.setattr(presentation, "_foreground_window", lambda: 123)
        monkeypatch.setattr(presentation, "_window_rect", lambda hwnd: (0, 0, 1920, 1080))
        monkeypatch.setattr(presentation, "_monitor_rect", lambda hwnd: (0, 0, 1920, 1080))
        assert presentation.foreground_is_fullscreen() is True

    def test_false_for_an_ordinary_maximized_window_that_leaves_the_taskbar(self, monkeypatch):
        """A maximized window's bottom edge stops short of the monitor's, unlike a
        real fullscreen surface — this is the distinction the whole check rests on."""
        monkeypatch.setattr(presentation, "_foreground_window", lambda: 123)
        monkeypatch.setattr(presentation, "_window_rect", lambda hwnd: (0, 0, 1920, 1040))
        monkeypatch.setattr(presentation, "_monitor_rect", lambda hwnd: (0, 0, 1920, 1080))
        assert presentation.foreground_is_fullscreen() is False

    def test_true_when_the_window_overhangs_the_monitor_slightly(self, monkeypatch):
        """>= rather than ==: a window a pixel or two larger than the monitor still
        reads as covering it, which some fullscreen implementations do."""
        monkeypatch.setattr(presentation, "_foreground_window", lambda: 123)
        monkeypatch.setattr(presentation, "_window_rect", lambda hwnd: (-1, -1, 1921, 1081))
        monkeypatch.setattr(presentation, "_monitor_rect", lambda hwnd: (0, 0, 1920, 1080))
        assert presentation.foreground_is_fullscreen() is True

    def test_false_when_there_is_no_foreground_window(self, monkeypatch):
        monkeypatch.setattr(presentation, "_foreground_window", lambda: None)
        assert presentation.foreground_is_fullscreen() is False

    def test_false_when_the_window_rect_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(presentation, "_foreground_window", lambda: 123)
        monkeypatch.setattr(presentation, "_window_rect", lambda hwnd: None)
        monkeypatch.setattr(presentation, "_monitor_rect", lambda hwnd: (0, 0, 1920, 1080))
        assert presentation.foreground_is_fullscreen() is False

    def test_false_when_the_monitor_rect_is_unavailable(self, monkeypatch):
        monkeypatch.setattr(presentation, "_foreground_window", lambda: 123)
        monkeypatch.setattr(presentation, "_window_rect", lambda hwnd: (0, 0, 1920, 1080))
        monkeypatch.setattr(presentation, "_monitor_rect", lambda hwnd: None)
        assert presentation.foreground_is_fullscreen() is False

    def test_false_on_an_unsupported_platform(self, monkeypatch):
        monkeypatch.setattr(presentation, "_IS_WINDOWS", False)
        assert presentation.foreground_is_fullscreen() is False
