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
