"""Launch-at-login, via the per-user Registry Run key.

No installer, no scheduled task, no elevation — a Run key entry is the lightest way to
start a tray app with Windows, and it is exactly as easy to remove as it was to add,
which matters for a checkbox a user might regret. Windows-only, reached through the
stdlib `winreg` module (no extra dependency), matching the pattern in :mod:`power`:
every public function has a safe fallback everywhere else, so calling this on a
platform that cannot do it is a silent no-op rather than an error the caller has to
guard against.
"""

from __future__ import annotations

import sys

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import winreg

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "PostureGuard"


def _launch_command() -> str:
    """The command Windows should run at login.

    A frozen PyInstaller build's own executable already *is* the app — no interpreter,
    no `-m`. In a source checkout there is no such executable, so the command re-invokes
    the same interpreter running this code with the package's entry module.
    """
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{sys.executable}" -m postureguard.app'


def enable() -> bool:
    """Add the Run key entry. Returns False if this platform cannot support it."""
    if not _IS_WINDOWS:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
        return True
    except OSError:
        return False


def disable() -> bool:
    """Remove the Run key entry. Returns True whether or not one was present."""
    if not _IS_WINDOWS:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass
        return True
    except OSError:
        return False


def is_enabled() -> bool:
    """Whether a Run key entry for this app currently exists."""
    if not _IS_WINDOWS:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, _VALUE_NAME)
        return True
    except OSError:
        return False


def apply(enabled: bool) -> None:
    """Converge the Run key with the setting. Best-effort: never raises."""
    if enabled:
        enable()
    else:
        disable()
