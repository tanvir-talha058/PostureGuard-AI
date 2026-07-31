"""Personal baseline capture and intra-session drift tracking.

Two different questions get answered here.

**Baseline** — "what does *this* person sitting well, at *this* camera, look like?"
Absolute anatomical constants misfire across body types and camera heights, so every
threshold downstream is expressed as a deviation from a short recording of the user
deliberately sitting up straight.

**Drift** — "have they been slowly sinking all afternoon?" Gradual collapse never trips
an instantaneous threshold; each frame is only marginally worse than the last. Comparing
a long rolling median against the baseline catches what per-frame checks cannot.

No camera or UI here — this operates on streams of :class:`PostureMetrics`.
"""

from __future__ import annotations

import json
import statistics
import time
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .metrics import PostureMetrics

#: Fewer good samples than this and the median is not worth trusting.
MIN_CALIBRATION_SAMPLES = 30

#: Rolling window for drift. Long enough that normal fidgeting averages out.
DRIFT_WINDOW_SECONDS = 600.0
MIN_DRIFT_SAMPLES = 120


@dataclass(frozen=True)
class Baseline:
    """A person's own good posture, as median metric values."""

    values: Mapping[str, float]
    sample_count: int = 0
    captured_at: str = ""

    def get(self, name: str) -> float | None:
        return self.values.get(name)

    def has(self, *names: str) -> bool:
        return all(self.values.get(n) is not None for n in names)

    def to_json(self) -> str:
        return json.dumps(
            {
                "values": dict(self.values),
                "sample_count": self.sample_count,
                "captured_at": self.captured_at,
            },
            indent=2,
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Baseline | None:
        """Return the stored baseline, or None if absent or unreadable.

        A corrupt file should send the user back through calibration, not crash the
        app on startup.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return cls(
                values={k: float(v) for k, v in raw["values"].items()},
                sample_count=int(raw.get("sample_count", 0)),
                captured_at=str(raw.get("captured_at", "")),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None


@dataclass
class BaselineBuilder:
    """Accumulates metric samples during the calibration countdown."""

    _samples: dict[str, list[float]] = field(default_factory=dict)
    _frames: int = 0

    def add(self, metrics: PostureMetrics) -> None:
        if not metrics.any_available():
            return
        self._frames += 1
        for name, value in metrics.as_dict().items():
            if value is not None:
                self._samples.setdefault(name, []).append(value)

    @property
    def frames(self) -> int:
        return self._frames

    def ready(self, minimum: int = MIN_CALIBRATION_SAMPLES) -> bool:
        return self._frames >= minimum

    def build(self, minimum: int = MIN_CALIBRATION_SAMPLES) -> Baseline:
        """Median per metric, keeping only metrics seen often enough to be reliable.

        A metric that flickered in and out during calibration — a hip glimpsed twice
        between desk and elbow — is dropped rather than baselined off two samples.
        """
        values = {
            name: statistics.median(samples)
            for name, samples in self._samples.items()
            if len(samples) >= minimum
        }
        return Baseline(
            values=values,
            sample_count=self._frames,
            captured_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )


class DriftTracker:
    """Rolling medians over a long window, for detecting slow collapse."""

    def __init__(
        self,
        window_seconds: float = DRIFT_WINDOW_SECONDS,
        min_samples: int = MIN_DRIFT_SAMPLES,
    ) -> None:
        self._window = window_seconds
        self._min_samples = min_samples
        self._samples: deque[tuple[float, dict[str, float]]] = deque()

    def add(self, metrics: PostureMetrics, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        present = {k: v for k, v in metrics.as_dict().items() if v is not None}
        if present:
            self._samples.append((now, present))
        self._expire(now)

    def _expire(self, now: float) -> None:
        cutoff = now - self._window
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def medians(self) -> dict[str, float]:
        """Median of each metric over the window, or empty until enough samples."""
        if len(self._samples) < self._min_samples:
            return {}
        collected: dict[str, list[float]] = {}
        for _, sample in self._samples:
            for name, value in sample.items():
                collected.setdefault(name, []).append(value)
        return {
            name: statistics.median(values)
            for name, values in collected.items()
            if len(values) >= self._min_samples
        }

    def reset(self) -> None:
        """Clear history — after a recalibration or a long break, it is stale."""
        self._samples.clear()


def baseline_from(samples: Iterable[PostureMetrics], minimum: int = 1) -> Baseline:
    """Convenience for tests and scripted calibration."""
    builder = BaselineBuilder()
    for sample in samples:
        builder.add(sample)
    return builder.build(minimum=minimum)
