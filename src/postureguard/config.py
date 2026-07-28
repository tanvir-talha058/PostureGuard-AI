"""User preferences, persisted as JSON.

Sensitivity is expressed as a single number rather than a wall of per-fault
thresholds. Someone adjusting how much the app nags them is answering one question —
"too twitchy or not twitchy enough" — and giving them six sliders to answer it just
moves the tuning burden onto the person least equipped to carry it.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .rules import Thresholds


@dataclass
class Config:
    # --- camera ---
    camera_index: int = 0
    mirror: bool = True

    # --- detection ---
    #: 1.0 is the calibrated default. Above 1 flags smaller deviations; below 1 is
    #: more forgiving. Scales every threshold together.
    sensitivity: float = 1.0
    #: Seconds of sustained bad posture before a fault is raised.
    react_after_seconds: float = 0.5

    # --- interventions ---
    alerts_enabled: bool = True
    toast_after_seconds: float = 25.0
    dim_enabled: bool = True
    dim_after_seconds: float = 60.0
    dim_max_opacity: float = 0.40
    snooze_minutes: int = 15

    # --- breaks ---
    breaks_enabled: bool = True
    break_interval_minutes: int = 40

    # --- mini window ---
    #: The compact always-on-top readout. On by default: it is the surface that makes
    #: correction possible while you are working, rather than when you go looking.
    mini_window: bool = True
    #: Collapsed to a single instruction bar, with no camera view or readings.
    mini_collapsed: bool = False
    #: Keeps the mini window above every other window, including maximized ones. On
    #: by default: a correction that can be buried behind whatever else is open stops
    #: correcting anything within minutes of daily use.
    mini_always_on_top: bool = True
    #: Last position on screen. -1 means "not placed yet, put it bottom-right".
    mini_x: int = -1
    mini_y: int = -1
    #: Name of the screen the mini window last lived on. Empty means "not recorded
    #: yet, use the primary screen". A saved position is only meaningful relative to
    #: the monitor it was placed on — reapplying raw coordinates against whatever
    #: screen happens to be primary today can drop the panel on the wrong display
    #: entirely when a second monitor is unplugged or the arrangement changes.
    mini_screen: str = ""

    # --- interventions: sound ---
    #: A short chime alongside the toast. Off by default — the visual ladder already
    #: covers the desk, and sound is the one channel that reaches past a phone or a
    #: second monitor, which also makes it the one most likely to be unwelcome
    #: unasked-for in a shared office.
    alert_sound_enabled: bool = False

    # --- interventions: presentation ---
    #: Hold every rung past the overlay cue while the foreground window is fullscreen
    #: — a screen-shared presentation, a video call, a game. A full-screen dim layer
    #: appearing mid-slide is the kind of failure that gets a tool like this uninstalled
    #: by the people it embarrassed, not just the person using it.
    suppress_when_fullscreen: bool = True

    # --- interventions: sensitivity backoff ---
    #: Snoozing the same fault repeatedly is the user telling the app it is too
    #: twitchy for their current setup, more directly than any slider. After enough
    #: snoozes in a day this nudges `sensitivity` down a step on its own, once, and
    #: says so — rather than requiring them to find Settings mid-workday.
    auto_backoff_enabled: bool = True

    # --- breaks: weekly summary ---
    #: A once-a-week notification naming the day and hour posture held up worst,
    #: built from history the app is already recording. Purely informational — it
    #: does not gate anything and can be turned off without affecting detection.
    weekly_summary_enabled: bool = True

    # --- calibration ---
    #: Name of the active baseline profile. Lets someone who splits time between an
    #: office desk and a home desk keep two calibrations rather than recalibrating
    #: twice a day. "default" always exists; others are created from Settings.
    calibration_profile: str = "default"

    # --- posture: standing ---
    #: A sitting baseline does not apply to a standing posture — the whole frame
    #: geometry shifts. When this is on, a sustained shift consistent with standing
    #: up switches the status to "standing" and suspends the sitting-calibrated fault
    #: checks rather than misapplying them, until the user sits back down.
    standing_detection_enabled: bool = True

    # --- appearance ---
    #: "dark" (the default instrument palette) or "light".
    theme_mode: str = "dark"

    # --- hotkeys ---
    #: Global keyboard shortcuts for Snooze and Recalibrate, reachable even when
    #: PostureGuard is not the focused window — the two actions someone reaches for
    #: without wanting to alt-tab away from what they were doing.
    hotkeys_enabled: bool = True

    # --- data ---
    #: How long session history is kept before it is purged automatically. 0 keeps
    #: it forever. Default chosen to bound growth (roughly 1.3 GB/year at 6h/day of
    #: use) while comfortably covering the History screen's longest range (30 days).
    retention_days: int = 180

    # --- power ---
    #: Release the camera while the Windows session is locked — nobody could
    #: plausibly be in frame, and a released device also turns its capture LED off.
    pause_when_locked: bool = True
    #: Release the camera after this many minutes with no keyboard/mouse input.
    #: 0 disables idle-based pausing.
    pause_after_idle_minutes: int = 10
    #: Halve the frame-capture rate while running on battery.
    battery_saver: bool = True

    # --- app ---
    start_minimized: bool = False
    launch_at_login: bool = False

    def thresholds(self, frame_rate: float = 30.0) -> Thresholds:
        """Detection thresholds implied by the current sensitivity.

        Higher sensitivity means a *smaller* deviation counts, so thresholds divide
        by it. Clamped so a slider at either end cannot produce a threshold of zero
        (everything faults) or infinity (nothing ever does).
        """
        scale = 1.0 / max(min(self.sensitivity, 2.0), 0.25)
        base = Thresholds()
        frames = max(int(self.react_after_seconds * frame_rate), 1)
        return Thresholds(
            forward_head_gap_drop=base.forward_head_gap_drop * scale,
            forward_head_face_rise=base.forward_head_face_rise * scale,
            screen_close_rise=base.screen_close_rise * scale,
            tilt_degrees=base.tilt_degrees * scale,
            torso_degrees=base.torso_degrees * scale,
            sink_units=base.sink_units * scale,
            enter_frames=frames,
            exit_frames=max(frames // 3, 1),
            exit_ratio=base.exit_ratio,
            drift_scale=base.drift_scale,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Config":
        """Read stored settings, falling back to defaults for anything unreadable.

        Settings are never load-bearing enough to justify failing startup, and an
        unknown key from a newer version should be ignored rather than fatal.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        if not isinstance(raw, dict):
            return cls()
        known = {f.name: f.type for f in fields(cls)}
        accepted = {}
        for key, value in raw.items():
            if key not in known:
                continue
            try:
                accepted[key] = value
            except (TypeError, ValueError):
                continue
        try:
            return cls(**accepted)
        except TypeError:
            return cls()
