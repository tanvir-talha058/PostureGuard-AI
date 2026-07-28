"""An optional chime alongside the toast.

The whole intervention ladder up to this point is visual — cue, toast, dim — which
structurally cannot reach someone looking at a phone, papers, or a second monitor with
nothing posture-related on it. A short system sound is the one channel that does. Off by
default: unlike a visual cue in your own peripheral vision, a sound is also heard by
whoever shares the room, so it opts in rather than assuming everyone wants it.

Windows-only, via the stdlib `winsound` module — no extra dependency, matching the
pattern in :mod:`power` and :mod:`autostart`: unsupported platforms get a silent no-op
rather than an error the caller has to guard against.
"""

from __future__ import annotations

import sys

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    import winsound


def play_alert() -> None:
    """A brief, unobtrusive notification sound. Never raises."""
    if not _IS_WINDOWS:
        return
    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except OSError:
        pass
