"""Global keyboard shortcuts for Snooze and Recalibrate.

Reachable even when PostureGuard is not the focused window, which is the whole point —
Qt's own `QShortcut` only fires while the app has focus, and the two actions someone
reaches for (silence the alerts, redo the baseline) are exactly the ones you want
without alt-tabbing away from whatever you were doing. Implemented with `RegisterHotKey`
plus a native event filter that catches `WM_HOTKEY`, the only way to get a truly global
shortcut on Windows.

Windows-only, through `ctypes`, matching the pattern in :mod:`power` and
:mod:`presentation`: the low-level platform calls are thin, single-purpose wrappers so
tests can monkeypatch them directly — critically, so a test run never actually registers
a real system-wide hotkey on the machine running it.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QAbstractNativeEventFilter

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wintypes

    _user32 = ctypes.windll.user32
    _WM_HOTKEY = 0x0312
    _MOD_ALT = 0x0001
    _MOD_CONTROL = 0x0002

#: Registration IDs, arbitrary but fixed and unique within this process.
SNOOZE_HOTKEY_ID = 0xB001
RECALIBRATE_HOTKEY_ID = 0xB002

#: Ctrl+Alt+P (Pause/snooze) and Ctrl+Alt+R (Recalibrate) — a modifier pair uncommon
#: enough in other software to be unlikely to collide, and mnemonic enough to remember
#: without looking it up.
_VK_P = 0x50
_VK_R = 0x52
_MODS = _MOD_CONTROL | _MOD_ALT if _IS_WINDOWS else 0


def _register(id_: int, vk: int) -> bool:
    if not _IS_WINDOWS:
        return False
    return bool(_user32.RegisterHotKey(None, id_, _MODS, vk))


def _unregister(id_: int) -> None:
    if not _IS_WINDOWS:
        return
    _user32.UnregisterHotKey(None, id_)


class GlobalHotkeys(QAbstractNativeEventFilter):
    """Registers the two hotkeys system-wide and dispatches WM_HOTKEY to callbacks.

    An instance must be kept alive for as long as it should stay installed — Qt does
    not hold a strong reference to a native event filter, so letting this get garbage
    collected silently stops delivering hotkey presses.
    """

    def __init__(self, on_snooze, on_recalibrate) -> None:
        super().__init__()
        self._on_snooze = on_snooze
        self._on_recalibrate = on_recalibrate
        self._registered = False

    def register(self) -> bool:
        """Attempt to claim both hotkeys. Best-effort: another app may already own
        one of them, which is not a reason to fail the whole feature — whichever
        registration succeeds still works."""
        if not _IS_WINDOWS or self._registered:
            return False
        snoozed = _register(SNOOZE_HOTKEY_ID, _VK_P)
        recalibrated = _register(RECALIBRATE_HOTKEY_ID, _VK_R)
        self._registered = snoozed or recalibrated
        return self._registered

    def unregister(self) -> None:
        if not self._registered:
            return
        _unregister(SNOOZE_HOTKEY_ID)
        _unregister(RECALIBRATE_HOTKEY_ID)
        self._registered = False

    def dispatch(self, hotkey_id: int) -> bool:
        """Route a WM_HOTKEY id to its callback. Returns True if it matched one.

        Split out from the native message parsing so the routing logic — the part
        actually worth getting right — is testable without a real Win32 MSG struct.
        """
        if hotkey_id == SNOOZE_HOTKEY_ID:
            self._on_snooze()
            return True
        if hotkey_id == RECALIBRATE_HOTKEY_ID:
            self._on_recalibrate()
            return True
        return False

    def nativeEventFilter(self, event_type, message):
        if _IS_WINDOWS and event_type == b"windows_generic_MSG":
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == _WM_HOTKEY:
                self.dispatch(msg.wParam)
        return False, 0
