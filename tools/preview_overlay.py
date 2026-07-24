"""Render the overlay offscreen with synthetic data, for design iteration.

Lets the panel be reviewed in every state — calibrating, in tolerance, faulted — without
sitting in front of a webcam and contorting to trigger each one.

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

import numpy as np  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from postureguard.calibration import baseline_from  # noqa: E402
from postureguard.landmarks import Landmarks, Point  # noqa: E402
from postureguard.metrics import compute_metrics  # noqa: E402
from postureguard.overlay import PostureOverlay, ViewModel  # noqa: E402
from postureguard.rules import RuleEngine, Thresholds  # noqa: E402

ASPECT = 4 / 3
FAST = Thresholds(enter_frames=1, exit_frames=1)


def scene(width: int = 640, height: int = 480) -> np.ndarray:
    """A stand-in for a webcam view: a soft vignette so guides can be judged in situ."""
    ys, xs = np.mgrid[0:height, 0:width]
    radial = np.sqrt(((xs - width / 2) / width) ** 2 + ((ys - height / 2) / height) ** 2)
    base = np.clip(150 - radial * 190, 25, 150)
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[..., 0] = base * 0.92  # B
    frame[..., 1] = base * 0.86  # G
    frame[..., 2] = base * 0.80  # R
    return frame


def pose(gap: float = 0.20, ocular: float = 0.09, shoulder_y: float = 0.62,
         width: float = 0.30, tilt: float = 0.0) -> Landmarks:
    cx = 0.5 * ASPECT
    ear_y = shoulder_y - gap
    eye_y = ear_y + 0.01

    def p(x_sq: float, y: float) -> Point:
        return Point(x=x_sq / ASPECT, y=y)

    return Landmarks(
        {
            "nose": p(cx, eye_y + 0.03),
            "right_eye": p(cx - ocular / 2, eye_y - tilt * 0.004),
            "left_eye": p(cx + ocular / 2, eye_y + tilt * 0.004),
            "right_ear": p(cx - width * 0.23, ear_y),
            "left_ear": p(cx + width * 0.23, ear_y),
            "right_shoulder": p(cx - width / 2, shoulder_y),
            "left_shoulder": p(cx + width / 2, shoulder_y),
            "right_hip": p(cx - width * 0.4, 0.95),
            "left_hip": p(cx + width * 0.4, 0.95),
        }
    )


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "preview"
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv[:1])
    frame = scene()

    upright = pose()
    baseline = baseline_from([compute_metrics(upright, ASPECT)])

    states = {
        "01-calibrating": ViewModel(
            frame=frame, landmarks=upright,
            metrics=compute_metrics(upright, ASPECT), baseline=None,
            aspect=ASPECT, status="calibrating",
            message="Sit tall — recording your baseline in 3",
        ),
        "02-in-tolerance": ViewModel(
            frame=frame, landmarks=upright,
            metrics=compute_metrics(upright, ASPECT), baseline=baseline,
            aspect=ASPECT, status="in_tolerance",
        ),
        "03-forward-head": None,
        "04-searching": ViewModel(
            frame=frame, landmarks=None, baseline=baseline,
            aspect=ASPECT, status="searching", message="Step into view",
        ),
    }

    craning = pose(gap=0.10, ocular=0.11, shoulder_y=0.66)
    craning_metrics = compute_metrics(craning, ASPECT)
    engine = RuleEngine(baseline, FAST)
    faults = engine.update(craning_metrics)
    states["03-forward-head"] = ViewModel(
        frame=frame, landmarks=craning, metrics=craning_metrics,
        faults=faults, baseline=baseline, aspect=ASPECT, status="fault",
    )

    overlay = PostureOverlay(FAST)
    for name, model in states.items():
        overlay.show_model(model)
        overlay.grab().save(str(out / f"{name}.png"))
        print(f"wrote {out / f'{name}.png'}")

    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
