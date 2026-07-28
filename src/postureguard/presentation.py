"""Detecting a fullscreen foreground window, to hold the louder rungs back.

A screen-shared presentation, a video call gone fullscreen, a game — none of these are
moments a full-screen dim layer should be answering bad posture with. The overlay cue
stays on regardless (it lives in the corner of a small always-on-top panel, not on top
of whatever is being shown to other people), but the toast and the dim layer are exactly
the two surfaces that would embarrass the user in front of an audience, so escalation
past the cue is held while this is true.

Windows-only, through `ctypes`, matching the pattern in :mod:`power`: every public
function has a safe fallback everywhere else, and each is a thin wrapper around a
private, single-purpose call so tests can monkeypatch the platform interaction directly.
"""

from __future__ import annotations

import sys

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wintypes

    class _Rect(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    class _MonitorInfo(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", _Rect),
            ("rcWork", _Rect),
            ("dwFlags", wintypes.DWORD),
        ]

    _user32 = ctypes.windll.user32
    _MONITOR_DEFAULTTONEAREST = 2


def _foreground_window() -> int | None:
    if not _IS_WINDOWS:
        return None
    hwnd = _user32.GetForegroundWindow()
    return hwnd or None


def _window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not _IS_WINDOWS:
        return None
    rect = _Rect()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


def _monitor_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if not _IS_WINDOWS:
        return None
    monitor = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    if not monitor:
        return None
    info = _MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    if not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    rect = info.rcMonitor
    return (rect.left, rect.top, rect.right, rect.bottom)


def foreground_is_fullscreen() -> bool:
    """True when the foreground window's bounds cover its entire monitor.

    A borderless or maximized-with-no-chrome window covering the full monitor is the
    signature of a presentation, a fullscreen video call, or a game — an ordinary
    maximized window still leaves the taskbar showing, which this comparison catches
    because its bottom edge falls short of the monitor's.
    """
    hwnd = _foreground_window()
    if hwnd is None:
        return False
    window = _window_rect(hwnd)
    monitor = _monitor_rect(hwnd)
    if window is None or monitor is None:
        return False
    w_left, w_top, w_right, w_bottom = window
    m_left, m_top, m_right, m_bottom = monitor
    return w_left <= m_left and w_top <= m_top and w_right >= m_right and w_bottom >= m_bottom
