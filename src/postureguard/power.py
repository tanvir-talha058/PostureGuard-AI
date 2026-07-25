"""Platform activity and power probes, for deciding when to release the camera.

Real implementations are Windows-only, reached through `ctypes` with **no extra
dependency** — verified reachable on the target machine before writing any of the
pause logic that depends on them. Every probe has a safe fallback everywhere else:
elsewhere the functions report "active, unlocked, on mains", which means the app
simply never pauses on a platform it cannot ask.

Each public function is a thin wrapper around a private, single-purpose call so tests
can monkeypatch the actual platform interaction without needing a real locked session
or a battery to unplug.
"""

from __future__ import annotations

import sys

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wintypes

    class _LastInputInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    class _SystemPowerStatus(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_byte),
            ("BatteryFlag", ctypes.c_byte),
            ("BatteryLifePercent", ctypes.c_byte),
            ("Reserved1", ctypes.c_byte),
            ("BatteryLifeTime", ctypes.c_ulong),
            ("BatteryFullLifeTime", ctypes.c_ulong),
        ]

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    # The interactive desktop cannot be opened while the workstation is locked, or
    # while a secure desktop (UAC prompt, Ctrl+Alt+Del) is in front of it — both cases
    # where nobody could plausibly be sitting in front of the camera this gates.
    _DESKTOP_SWITCHDESKTOP = 0x0100


def _get_last_input_tick() -> int | None:
    """Raw GetLastInputInfo tick, or None if the platform call is unavailable."""
    if not _IS_WINDOWS:
        return None
    info = _LastInputInfo()
    info.cbSize = ctypes.sizeof(info)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    return info.dwTime


def _get_tick_count() -> int:
    if not _IS_WINDOWS:
        return 0
    return _kernel32.GetTickCount()


def _can_open_input_desktop() -> bool | None:
    """Whether the interactive desktop opened, or None if unsupported here."""
    if not _IS_WINDOWS:
        return None
    handle = _user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
    if not handle:
        return False
    _user32.CloseDesktop(handle)
    return True


def _ac_line_status() -> int | None:
    """0 = on battery, 1 = plugged in, 255 = unknown, None if unsupported."""
    if not _IS_WINDOWS:
        return None
    status = _SystemPowerStatus()
    if not _kernel32.GetSystemPowerStatus(ctypes.byref(status)):
        return None
    return status.ACLineStatus


def idle_seconds() -> float:
    """Seconds since the last keyboard or mouse input, system-wide.

    This is activity, not attention — it cannot see someone reading the screen — and
    it correctly does not try to. It only answers "has anyone touched this machine
    recently", which is what deciding to release the camera actually needs.
    """
    last = _get_last_input_tick()
    if last is None:
        return 0.0
    return max(_get_tick_count() - last, 0) / 1000.0


def session_locked() -> bool:
    """True while the Windows session is locked or a secure desktop is active."""
    opened = _can_open_input_desktop()
    if opened is None:
        return False
    return not opened


def on_battery() -> bool:
    """True when running off battery rather than plugged into mains power.

    Only a confirmed battery reading counts; "plugged in" and "unknown" both leave
    the frame rate at its normal setting rather than guessing.
    """
    return _ac_line_status() == 0
