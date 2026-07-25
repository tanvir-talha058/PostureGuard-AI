"""Where PostureGuard keeps its local state.

One place, so the privacy promise is auditable: everything the app persists lives under
:func:`data_dir`, and none of it is imagery. Baselines and session statistics only.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "PostureGuard"


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


def baseline_path() -> Path:
    return data_dir() / "baseline.json"


def config_path() -> Path:
    return data_dir() / "config.json"


def database_path() -> Path:
    return data_dir() / "sessions.db"


def break_state_path() -> Path:
    return data_dir() / "break_state.json"
