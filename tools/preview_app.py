"""Render every screen offscreen with seeded data, for design review.

Builds a throwaway session database with a fortnight of plausible history so the
History screen has something real to draw, then grabs each screen to a PNG.

    python tools/preview_app.py [output_dir]
"""

from __future__ import annotations

import os
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)  # the offscreen plugin has no fonts

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from postureguard import theme  # noqa: E402
from postureguard.config import Config  # noqa: E402
from postureguard.rules import Fault, FaultKind  # noqa: E402
from postureguard.session import SessionStore  # noqa: E402
from postureguard.ui.design import stylesheet  # noqa: E402
from postureguard.ui.screens.exercises import ExercisesScreen  # noqa: E402
from postureguard.ui.screens.history import HistoryScreen  # noqa: E402
from postureguard.ui.screens.live import LiveScreen  # noqa: E402
from postureguard.ui.screens.settings import SettingsScreen  # noqa: E402
from postureguard.ui.window import MainWindow  # noqa: E402

FAULTS = {
    FaultKind.FORWARD_HEAD: Fault(FaultKind.FORWARD_HEAD, 2.2, "Pull your chin back.", ()),
    FaultKind.SPINE_FLEXION: Fault(FaultKind.SPINE_FLEXION, 1.6, "Sit tall.", ()),
    FaultKind.LATERAL_TILT: Fault(FaultKind.LATERAL_TILT, 1.3, "Level out.", ()),
    FaultKind.SCREEN_TOO_CLOSE: Fault(FaultKind.SCREEN_TOO_CLOSE, 1.4, "Push back.", ()),
}


def seed(store: SessionStore, today: date, days: int = 14) -> None:
    """A fortnight of plausible desk days, weekends off."""
    rng = random.Random(7)
    for offset in range(days):
        day = today - timedelta(days=days - 1 - offset)
        if day.weekday() >= 5:
            continue  # weekends left genuinely blank, to exercise the gap rendering
        # Posture reliably decays through the afternoon.
        for hour in range(9, 18):
            decay = (hour - 9) / 9
            good_ratio = max(0.9 - decay * 0.45 + rng.uniform(-0.08, 0.08), 0.15)
            minutes = rng.randint(35, 55)
            for second in range(minutes):
                stamp = datetime(day.year, day.month, day.day, hour).timestamp() + second * 60
                if rng.random() < good_ratio:
                    store.log("in_tolerance", (), when=stamp)
                else:
                    kind = rng.choices(
                        list(FAULTS),
                        weights=[5, 3, 2, 2],
                    )[0]
                    store.log("fault", (FAULTS[kind],), when=stamp)


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs" / "preview"
    out.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv[:1])
    app.setStyleSheet(stylesheet())

    store = SessionStore()
    seed(store, date.today())

    config = Config()
    window = MainWindow()
    window.resize(*theme.WINDOW_SIZE)

    live = LiveScreen(config.thresholds(), store)
    history = HistoryScreen(store)
    exercises = ExercisesScreen(store)
    settings = SettingsScreen(config)

    window.add_screen("live", live)
    window.add_screen("history", history)
    window.add_screen("exercises", exercises)
    window.add_screen("settings", settings)

    for key in ("live", "history", "exercises", "settings"):
        window.show_screen(key)
        app.processEvents()
        path = out / f"app-{key}.png"
        window.grab().save(str(path))
        print(f"wrote {path}")

    store.close()
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
