"""Render the mini window offscreen with synthetic data, for design iteration.

Lets the panel be reviewed in every state — calibrating, in tolerance, faulted,
escalated, collapsed — without sitting in front of a webcam and contorting to trigger
each one.

The mini window no longer shows a camera feed (see overlay.py's module docstring for
why), so unlike earlier versions of this tool there is no synthetic frame or skeleton
to build — just the metrics, faults and status the panel actually reads.

    python tools/preview_overlay.py [output_dir]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Render on the native platform, not "offscreen". The offscreen QPA plugin ships with
# an empty font database, so every glyph comes out as tofu and the preview is useless
# for judging type. QWidget.grab() renders a never-shown widget fine on the real
# platform, so nothing has to appear on screen.
os.environ.pop("QT_QPA_PLATFORM", None)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from postureguard.metrics import PostureMetrics  # noqa: E402
from postureguard.overlay import PostureOverlay, ViewModel  # noqa: E402
from postureguard.rules import Fault, FaultKind  # noqa: E402

GOOD_METRICS = PostureMetrics(
    head_shoulder_gap=0.667, face_scale=0.300, screen_distance=0.090,
    shoulder_roll=0.0, eye_roll=0.0, torso_angle=0.0, shoulder_height=0.620,
)
CRANING_METRICS = PostureMetrics(
    head_shoulder_gap=0.333, face_scale=0.367, screen_distance=0.113,
    shoulder_roll=0.0, eye_roll=0.0, torso_angle=0.0, shoulder_height=0.660,
)

FORWARD_HEAD = Fault(
    FaultKind.FORWARD_HEAD, 3.3,
    "Pull your chin straight back and stack your ears over your shoulders.",
    ("left_ear", "right_ear", "left_shoulder", "right_shoulder"),
)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "preview"
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv[:1])

    states = {
        "01-calibrating": ViewModel(
            metrics=GOOD_METRICS, status="calibrating",
            message="Sit tall — baseline in 3",
        ),
        "02-in-tolerance": ViewModel(metrics=GOOD_METRICS, status="in_tolerance"),
        "03-forward-head": ViewModel(
            metrics=CRANING_METRICS, faults=[FORWARD_HEAD], status="fault",
            urgency=1, held_seconds=6.0,
        ),
        # The same fault after it has been ignored long enough to escalate: brighter
        # border, and the held time explains why the panel started asking louder.
        "05-escalated": ViewModel(
            metrics=CRANING_METRICS, faults=[FORWARD_HEAD], status="fault",
            urgency=3, held_seconds=68.0,
        ),
        "04-searching": ViewModel(status="searching", message="Step into view"),
        "06-paused": ViewModel(status="paused", message="Paused — no activity detected"),
        "07-camera-lost": ViewModel(status="camera_lost", message="Camera disconnected"),
    }

    overlay = PostureOverlay()
    for name, model in states.items():
        overlay.show_model(model)
        overlay.grab().save(str(out / f"{name}.png"))
        print(f"wrote {out / f'{name}.png'}")

    # Collapsed: the same states as a single instruction bar.
    overlay.set_collapsed(True)
    for name in ("02-in-tolerance", "03-forward-head", "05-escalated", "01-calibrating"):
        overlay.show_model(states[name])
        path = out / f"bar-{name.split('-', 1)[1]}.png"
        overlay.grab().save(str(path))
        print(f"wrote {path}")

    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
