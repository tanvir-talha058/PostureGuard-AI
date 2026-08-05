"""Where PostureGuard keeps its local state.

One place, so the privacy promise is auditable: everything the app persists lives under
:func:`data_dir`, and none of it is imagery. Baselines and session statistics only.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

APP_NAME = "PostureGuard"

#: The profile every install has implicitly had since before named profiles existed.
#: Its baseline lives at the original top-level path so upgrading never orphans an
#: existing calibration or forces a surprise recalibration.
DEFAULT_PROFILE = "default"


def data_dir() -> Path:
    """Per-user application data directory, created on demand."""
    override = os.environ.get("POSTUREGUARD_HOME")
    if override:
        path = Path(override)
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
        path = Path(base) / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share"
        path = Path(base) / APP_NAME.lower()
    path.mkdir(parents=True, exist_ok=True)
    return path


def model_dir() -> Path:
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sanitize_profile_name(name: str) -> str:
    """A filesystem-safe profile identifier, and the *only* place this project
    turns a name a user typed into a path component.

    The sanitized result is what gets stored in `Config.calibration_profile` and
    shown back to the user — never a separate "pretty name" kept alongside a
    different slug on disk. Two representations of the same profile is exactly how
    a picker and a filename quietly drift apart; one representation cannot.
    """
    slug = re.sub(r"[^A-Za-z0-9 _-]+", "-", name.strip()).strip("-")
    return slug or "profile"


def baselines_dir() -> Path:
    path = data_dir() / "baselines"
    path.mkdir(parents=True, exist_ok=True)
    return path


def baseline_path(profile: str = DEFAULT_PROFILE) -> Path:
    if profile == DEFAULT_PROFILE:
        return data_dir() / "baseline.json"
    return baselines_dir() / f"{profile}.json"


def list_profiles() -> list[str]:
    """Every profile with a saved baseline, "default" first, the rest alphabetical.

    "default" always appears even before its first calibration — it is the profile
    every install starts on, and a picker that omits it until first use would be a
    picker with nothing to pick on a fresh install.
    """
    named = sorted(p.stem for p in baselines_dir().glob("*.json"))
    return [DEFAULT_PROFILE, *named]


def config_path() -> Path:
    return data_dir() / "config.json"


def database_path() -> Path:
    return data_dir() / "sessions.db"


def break_state_path() -> Path:
    return data_dir() / "break_state.json"


def snooze_backoff_path() -> Path:
    return data_dir() / "snooze_backoff.json"


def weekly_summary_path() -> Path:
    return data_dir() / "weekly_summary.json"


def cue_variants_path() -> Path:
    return data_dir() / "cue_variants.json"


def monitor_profiles_path() -> Path:
    return data_dir() / "monitor_profiles.json"
