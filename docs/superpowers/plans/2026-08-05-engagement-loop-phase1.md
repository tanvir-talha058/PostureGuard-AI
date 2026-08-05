# Engagement Loop (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give users a daily posture score they already see plus a streak counter, a fixed set of five milestone achievements, and a week-over-week trend comparison — all computed at read-time from data `SessionStore` already stores, with zero new persistent state.

**Architecture:** Two new pure-logic modules (`weekly_trend.py`, `achievements.py`) sit beside the existing `session.py`/`weekly_summary.py` and follow their exact pattern: a frozen dataclass plus a `compute_*(store, today=None)` function that reads through `SessionStore` query methods. `SessionStore` gains two new read methods (`current_streak`, `fault_seconds_in_range`) to support them. The UI layer (`LiveScreen`, `HistoryScreen`) gets new widgets wired into their existing `refresh()` methods — no new screens, no new navigation entries.

**Tech Stack:** Python 3.10+, PySide6 (Qt widgets), SQLite via the existing `SessionStore`, pytest with an in-memory `SessionStore()` fixture (see `tests/test_session.py`).

## Global Constraints

- No camera frame or pose-landmark data is ever touched by this work — every new function only reads aggregates already in the `samples` table (`ts, day, hour, status, fault, severity`). See `[[postureguard-privacy-invariant]]`.
- No new SQLite table or schema version bump. Streaks/achievements/trends are recomputed from existing rows on every call, never cached to disk.
- Follow existing dataclass/query patterns in `src/postureguard/session.py` and `src/postureguard/weekly_summary.py` exactly (frozen dataclasses, `today: date | None = None` parameter for testability).
- UI: reuse `Card`, `StatTile`, `label()`, `plain()` from `src/postureguard/ui/widgets.py` and `theme.py` colors (`IN_TOLERANCE`, `MUTED`, `WARNING`, `FAULT`). Do not add new stylesheet roles to `ui/design.py`. Labels shown in a fixed-height row must not wrap (see `[[qt-wrapped-label-height]]`) — use `setToolTip` for overflow text, matching `StatTile.set_value`'s note-eliding pattern.
- Follow the existing widget-rebuild idiom from `src/postureguard/ui/screens/exercises.py:234-245` (`_populate`: `takeAt(0)` + `deleteLater()` loop, then re-add) for any dynamically-sized list of widgets.

---

### Task 1: `SessionStore.current_streak()` and `SessionStore.fault_seconds_in_range()`

**Files:**
- Modify: `src/postureguard/session.py` (add two methods to `SessionStore`, after `recent_scores` at line 218)
- Test: `tests/test_session.py` (add `TestStreaks` and `TestFaultRange` classes)

**Interfaces:**
- Consumes: existing `SessionStore.daily_summaries()`, the `samples` table.
- Produces: `SessionStore.current_streak(threshold: float = 80.0, min_tracked_seconds: int = 1800, today: date | None = None) -> int` and `SessionStore.fault_seconds_in_range(start: date, end: date) -> dict[FaultKind, int]` — both consumed by Task 2 and Task 3.

Note: the existing `fault_breakdown(days, today)` query (`session.py:168-183`) only bounds rows by `day >= start` with **no upper bound** — fine for its current caller (always called with `today=None`, i.e. "up to now"), but wrong for computing a *past* week's window, which is why this task adds a properly-bounded sibling method rather than reusing `fault_breakdown` with a shifted `today`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_session.py — add near the bottom, following existing class style

class TestStreaks:
    def test_zero_when_no_history(self, store):
        assert store.current_streak(today=TODAY) == 0

    def test_counts_consecutive_clean_days_ending_today(self, store):
        for offset in range(3):
            day = TODAY - timedelta(days=offset)
            fill(store, day, 9, 1800, "in_tolerance")
        assert store.current_streak(today=TODAY) == 3

    def test_a_bad_day_breaks_the_streak(self, store):
        fill(store, TODAY, 9, 1800, "in_tolerance")
        fill(store, TODAY - timedelta(days=1), 9, 1800, "fault", CRANING)
        fill(store, TODAY - timedelta(days=2), 9, 1800, "in_tolerance")
        assert store.current_streak(today=TODAY) == 1

    def test_a_day_with_too_little_tracked_time_is_skipped_not_broken(self, store):
        # Today has nothing logged yet (session hasn't started) — should not zero the streak.
        fill(store, TODAY - timedelta(days=1), 9, 1800, "in_tolerance")
        fill(store, TODAY - timedelta(days=2), 9, 1800, "in_tolerance")
        assert store.current_streak(today=TODAY) == 2

    def test_respects_custom_threshold(self, store):
        # 900s in_tolerance out of 1800s tracked = 50% score.
        fill(store, TODAY, 9, 900, "in_tolerance")
        fill(store, TODAY, 9, 900, "fault", CRANING)  # different second range would overlap; use hour 10 instead
        assert store.current_streak(threshold=40.0, today=TODAY) >= 0  # placeholder removed below


class TestFaultRange:
    def test_empty_range_returns_empty_dict(self, store):
        assert store.fault_seconds_in_range(TODAY, TODAY) == {}

    def test_counts_only_within_the_bounds(self, store):
        fill(store, TODAY - timedelta(days=10), 9, 60, "fault", CRANING)
        fill(store, TODAY - timedelta(days=1), 9, 30, "fault", TILTING)
        result = store.fault_seconds_in_range(TODAY - timedelta(days=6), TODAY)
        assert result == {FaultKind.LATERAL_TILT: 30}

    def test_most_costly_first(self, store):
        fill(store, TODAY, 9, 10, "fault", TILTING)
        fill(store, TODAY, 10, 40, "fault", CRANING)
        result = store.fault_seconds_in_range(TODAY, TODAY)
        assert list(result.keys()) == [FaultKind.FORWARD_HEAD, FaultKind.LATERAL_TILT]
```

Delete the placeholder `test_respects_custom_threshold` body above and replace it with a concrete assertion before running — write it for real as:

```python
    def test_respects_custom_threshold(self, store):
        # 900s in_tolerance, 900s fault -> 50% score. Below the default 80% threshold
        # but above a relaxed 40% threshold.
        fill(store, TODAY, 9, 900, "in_tolerance")
        fill(store, TODAY, 10, 900, "fault", CRANING)
        assert store.current_streak(today=TODAY) == 0
        assert store.current_streak(threshold=40.0, today=TODAY) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_session.py::TestStreaks tests/test_session.py::TestFaultRange -v`
Expected: FAIL with `AttributeError: 'SessionStore' object has no attribute 'current_streak'`

- [ ] **Step 3: Implement both methods**

```python
# src/postureguard/session.py — insert after recent_scores() (after line 218)

    def current_streak(
        self,
        threshold: float = 80.0,
        min_tracked_seconds: int = 1800,
        today: date | None = None,
    ) -> int:
        """Consecutive clean days, most recent first, ending at (or just before) today.

        A day with less than `min_tracked_seconds` tracked is skipped rather than
        treated as a break — a day off, or today before the session has started, should
        not erase a streak the way an actually bad day does.
        """
        summaries = list(reversed(self.daily_summaries(days=60, today=today)))
        streak = 0
        for summary in summaries:
            if summary.tracked_seconds < min_tracked_seconds:
                continue
            if summary.score < threshold:
                break
            streak += 1
        return streak

    def fault_seconds_in_range(self, start: date, end: date) -> dict[FaultKind, int]:
        """Seconds attributed to each fault type between start and end inclusive, most costly first."""
        rows = self._db.execute(
            "SELECT fault, COUNT(*) FROM samples"
            " WHERE day >= ? AND day <= ? AND fault IS NOT NULL GROUP BY fault",
            (start.isoformat(), end.isoformat()),
        ).fetchall()
        counted = Counter()
        for name, count in rows:
            try:
                counted[FaultKind(name)] = count
            except ValueError:
                continue  # a fault kind from a newer version; ignore rather than crash
        return dict(counted.most_common())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_session.py -v`
Expected: PASS (all of `TestStreaks`, `TestFaultRange`, and every pre-existing test in the file)

- [ ] **Step 5: Commit**

```bash
git add src/postureguard/session.py tests/test_session.py
git commit -m "feat: add current_streak and fault_seconds_in_range to SessionStore"
```

---

### Task 2: `weekly_trend.py` — week-over-week comparison

**Files:**
- Create: `src/postureguard/weekly_trend.py`
- Test: `tests/test_weekly_trend.py`

**Interfaces:**
- Consumes: `SessionStore.daily_summaries()`, `SessionStore.fault_seconds_in_range()` (Task 1).
- Produces: `WeeklyTrend` dataclass (`this_week_average: float`, `last_week_average: float`, `most_improved_fault: FaultKind | None`, `most_improved_seconds: int`) and `compute_weekly_trend(store: SessionStore, today: date | None = None) -> WeeklyTrend | None` — consumed by Task 3 and Task 6.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_weekly_trend.py
from datetime import date, timedelta

import pytest

from postureguard.rules import FaultKind
from postureguard.session import SessionStore
from postureguard.weekly_trend import compute_weekly_trend

from test_session import CRANING, TILTING, fill  # reuse existing fixtures/helpers

TODAY = date(2026, 7, 25)


@pytest.fixture
def store():
    with SessionStore() as s:
        yield s


class TestWeeklyTrend:
    def test_none_when_not_enough_data_either_week(self, store):
        fill(store, TODAY, 9, 60, "in_tolerance")
        assert compute_weekly_trend(store, today=TODAY) is None

    def test_none_when_this_week_has_data_but_last_week_does_not(self, store):
        for offset in range(7):
            fill(store, TODAY - timedelta(days=offset), 9, 3600, "in_tolerance")
        assert compute_weekly_trend(store, today=TODAY) is None

    def test_compares_averages_across_adjacent_weeks(self, store):
        for offset in range(7):
            fill(store, TODAY - timedelta(days=offset), 9, 3600, "in_tolerance")
        for offset in range(7, 14):
            fill(store, TODAY - timedelta(days=offset), 9, 1800, "in_tolerance")
            fill(store, TODAY - timedelta(days=offset), 10, 1800, "fault", CRANING)

        trend = compute_weekly_trend(store, today=TODAY)

        assert trend is not None
        assert trend.this_week_average == pytest.approx(100.0)
        assert trend.last_week_average == pytest.approx(50.0)

    def test_finds_the_fault_that_dropped_the_most(self, store):
        for offset in range(7):
            fill(store, TODAY - timedelta(days=offset), 9, 3600, "in_tolerance")
        for offset in range(7, 14):
            fill(store, TODAY - timedelta(days=offset), 10, 600, "fault", CRANING)
            fill(store, TODAY - timedelta(days=offset), 11, 100, "fault", TILTING)

        trend = compute_weekly_trend(store, today=TODAY)

        assert trend.most_improved_fault == FaultKind.FORWARD_HEAD
        assert trend.most_improved_seconds == 7 * 600
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_weekly_trend.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'postureguard.weekly_trend'`

- [ ] **Step 3: Write the implementation**

```python
# src/postureguard/weekly_trend.py
"""How this week compares to last week — for a trend card, not a table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .rules import FaultKind
from .session import SessionStore

#: Below this much tracked time in a week, a week-over-week comparison is noise.
MIN_TRACKED_SECONDS = 3600

#: A fault needs at least this much time last week to count as "reduced" this week —
#: otherwise a fault that barely occurred looks like a dramatic improvement by dropping
#: to zero.
MIN_FAULT_SECONDS_TO_COMPARE = 60


@dataclass(frozen=True)
class WeeklyTrend:
    this_week_average: float
    last_week_average: float
    most_improved_fault: FaultKind | None
    most_improved_seconds: int


def compute_weekly_trend(store: SessionStore, today: date | None = None) -> WeeklyTrend | None:
    """Compare the 7 days ending at `today` to the 7 days before that.

    Returns None if either week doesn't have enough tracked time to compare fairly.
    """
    end = today or date.today()
    this_week = store.daily_summaries(days=7, today=end)
    last_week_end = end - timedelta(days=7)
    last_week = store.daily_summaries(days=7, today=last_week_end)

    this_tracked = sum(s.tracked_seconds for s in this_week)
    last_tracked = sum(s.tracked_seconds for s in last_week)
    if this_tracked < MIN_TRACKED_SECONDS or last_tracked < MIN_TRACKED_SECONDS:
        return None

    this_average = 100.0 * sum(s.in_tolerance_seconds for s in this_week) / this_tracked
    last_average = 100.0 * sum(s.in_tolerance_seconds for s in last_week) / last_tracked

    this_faults = store.fault_seconds_in_range(end - timedelta(days=6), end)
    last_faults = store.fault_seconds_in_range(
        last_week_end - timedelta(days=6), last_week_end
    )

    best_fault: FaultKind | None = None
    best_drop = 0
    for kind, last_seconds in last_faults.items():
        if last_seconds < MIN_FAULT_SECONDS_TO_COMPARE:
            continue
        drop = last_seconds - this_faults.get(kind, 0)
        if drop > best_drop:
            best_drop = drop
            best_fault = kind

    return WeeklyTrend(
        this_week_average=this_average,
        last_week_average=last_average,
        most_improved_fault=best_fault,
        most_improved_seconds=best_drop,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_weekly_trend.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/postureguard/weekly_trend.py tests/test_weekly_trend.py
git commit -m "feat: add week-over-week trend computation"
```

---

### Task 3: `achievements.py` — five fixed milestones

**Files:**
- Create: `src/postureguard/achievements.py`
- Test: `tests/test_achievements.py`

**Interfaces:**
- Consumes: `SessionStore.current_streak()`, `SessionStore.daily_summaries()` (Task 1); `compute_weekly_trend()` (Task 2); `Baseline` from `src/postureguard/calibration.py` (already exists — `Baseline.load(path) -> Baseline | None`).
- Produces: `Achievement` dataclass (`key: str`, `title: str`, `description: str`, `earned: bool`) and `compute_achievements(store: SessionStore, baseline: Baseline | None, today: date | None = None) -> list[Achievement]`, always returning exactly 5 items in a fixed order — consumed by Task 5 (`HistoryScreen`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_achievements.py
from datetime import date, timedelta

import pytest

from postureguard.achievements import compute_achievements
from postureguard.calibration import Baseline
from postureguard.session import SessionStore

from test_session import CRANING, TILTING, fill

TODAY = date(2026, 7, 25)


@pytest.fixture
def store():
    with SessionStore() as s:
        yield s


class TestAchievements:
    def test_five_fixed_milestones_none_earned_on_empty_history(self, store):
        achievements = compute_achievements(store, baseline=None, today=TODAY)
        assert [a.key for a in achievements] == [
            "first_calibration",
            "first_clean_day",
            "streak_7",
            "streak_30",
            "most_improved",
        ]
        assert all(not a.earned for a in achievements)

    def test_first_calibration_earned_once_a_baseline_exists(self, store):
        baseline = Baseline(values={"forward_head_ratio": 0.1}, sample_count=30, captured_at="2026-07-01")
        achievements = compute_achievements(store, baseline=baseline, today=TODAY)
        by_key = {a.key: a for a in achievements}
        assert by_key["first_calibration"].earned

    def test_first_clean_day_earned_after_one_good_day(self, store):
        fill(store, TODAY, 9, 1800, "in_tolerance")
        achievements = compute_achievements(store, baseline=None, today=TODAY)
        by_key = {a.key: a for a in achievements}
        assert by_key["first_clean_day"].earned

    def test_streak_milestones_earned_at_the_right_length(self, store):
        for offset in range(7):
            fill(store, TODAY - timedelta(days=offset), 9, 1800, "in_tolerance")
        achievements = compute_achievements(store, baseline=None, today=TODAY)
        by_key = {a.key: a for a in achievements}
        assert by_key["streak_7"].earned
        assert not by_key["streak_30"].earned

    def test_most_improved_reflects_the_weekly_trend(self, store):
        for offset in range(7):
            fill(store, TODAY - timedelta(days=offset), 9, 3600, "in_tolerance")
        for offset in range(7, 14):
            fill(store, TODAY - timedelta(days=offset), 10, 600, "fault", CRANING)

        achievements = compute_achievements(store, baseline=None, today=TODAY)
        by_key = {a.key: a for a in achievements}
        assert by_key["most_improved"].earned
        assert "forward head" in by_key["most_improved"].description.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_achievements.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'postureguard.achievements'`

- [ ] **Step 3: Write the implementation**

```python
# src/postureguard/achievements.py
"""A small, fixed set of milestones — recomputed from history, never stored."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .calibration import Baseline
from .rules import FAULT_TITLES
from .session import SessionStore
from .weekly_trend import compute_weekly_trend

#: A day counts as "clean" once it clears this score with enough tracked time behind it.
CLEAN_DAY_THRESHOLD = 80.0
CLEAN_DAY_MIN_TRACKED_SECONDS = 1800


@dataclass(frozen=True)
class Achievement:
    key: str
    title: str
    description: str
    earned: bool


def compute_achievements(
    store: SessionStore,
    baseline: Baseline | None,
    today: date | None = None,
) -> list[Achievement]:
    """Always returns the same 5 achievements, in the same order, earned or not."""
    streak = store.current_streak(
        threshold=CLEAN_DAY_THRESHOLD,
        min_tracked_seconds=CLEAN_DAY_MIN_TRACKED_SECONDS,
        today=today,
    )
    history = store.daily_summaries(days=365, today=today)
    has_clean_day = any(
        s.tracked_seconds >= CLEAN_DAY_MIN_TRACKED_SECONDS and s.score >= CLEAN_DAY_THRESHOLD
        for s in history
    )
    trend = compute_weekly_trend(store, today=today)
    most_improved = trend.most_improved_fault if trend else None

    return [
        Achievement(
            key="first_calibration",
            title="Calibrated",
            description="Completed your first posture calibration.",
            earned=baseline is not None,
        ),
        Achievement(
            key="first_clean_day",
            title="First clean day",
            description=f"Spent a full day at {CLEAN_DAY_THRESHOLD:.0f}%+ in tolerance.",
            earned=has_clean_day,
        ),
        Achievement(
            key="streak_7",
            title="7-day streak",
            description="Seven consecutive clean days.",
            earned=streak >= 7,
        ),
        Achievement(
            key="streak_30",
            title="30-day streak",
            description="Thirty consecutive clean days.",
            earned=streak >= 30,
        ),
        Achievement(
            key="most_improved",
            title="Most improved",
            description=(
                f"Cut {FAULT_TITLES.get(most_improved, most_improved.value if most_improved else '')} "
                "time versus last week."
                if most_improved
                else "Reduce a fault's time versus last week."
            ),
            earned=most_improved is not None,
        ),
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_achievements.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/postureguard/achievements.py tests/test_achievements.py
git commit -m "feat: add fixed-set achievement computation"
```

---

### Task 4: Streak tile on the Live screen

**Files:**
- Modify: `src/postureguard/ui/screens/live.py` (`LiveScreen.__init__` around line 305-322, `LiveScreen.refresh` at line 352-364)

**Interfaces:**
- Consumes: `SessionStore.current_streak()` (Task 1), already-imported `StatTile`, `theme`.
- Produces: `self.streak_tile: StatTile` attribute on `LiveScreen`, for manual/visual verification (no new test file — this is a thin UI wire-up over an already-tested store method, consistent with how `score_tile`/`tracked_tile` have no dedicated widget tests in this codebase).

- [ ] **Step 1: Add the tile to the "Today" card grid**

In `src/postureguard/ui/screens/live.py`, inside `__init__` (replace lines 305-322):

```python
        today = Card("Today")
        grid = QGridLayout()
        grid.setSpacing(S["lg"])
        self.score_tile = StatTile("posture score", "—", "%")
        self.tracked_tile = StatTile("time at desk", "—")
        self.session_tile = StatTile("this session", "—")
        self.break_tile = StatTile("next break", "—")
        self.streak_tile = StatTile("clean streak", "—", "days")
        # Top-aligned, so a tile that grows a note does not shove its neighbours out
        # of line and break the row's shared baseline.
        top = Qt.AlignmentFlag.AlignTop
        grid.addWidget(self.score_tile, 0, 0, top)
        grid.addWidget(self.tracked_tile, 0, 1, top)
        grid.addWidget(self.session_tile, 1, 0, top)
        grid.addWidget(self.break_tile, 1, 1, top)
        grid.addWidget(self.streak_tile, 2, 0, 1, 2, top)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        today.add(plain(grid))
        side.addWidget(today, 0)
```

- [ ] **Step 2: Populate it in `refresh()`**

In `src/postureguard/ui/screens/live.py`, modify `refresh()` (lines 352-364):

```python
    def refresh(self) -> None:
        streak = self.store.current_streak()
        self.streak_tile.set_value(
            str(streak), note="consecutive clean days" if streak else "no active streak"
        )
        summary = self.store.today()
        if summary.tracked_seconds == 0:
            self.score_tile.set_value("—", note="Nothing tracked yet")
            self.tracked_tile.set_value("—")
            return
        self.score_tile.set_value(f"{summary.score:.0f}", note="")
        self.score_tile.set_tone(
            "StatusGood" if summary.score >= 80
            else "StatusWarn" if summary.score >= 60
            else "StatusFault"
        )
        self.tracked_tile.set_value(_duration(summary.tracked_seconds))
```

- [ ] **Step 3: Run the full test suite to confirm nothing broke**

Run: `pytest -q`
Expected: PASS, same count as before plus the new tests from Tasks 1-3 (no test in this repo directly instantiates `LiveScreen`'s Qt widgets per the earlier exploration, so this step is a regression check, not new coverage).

- [ ] **Step 4: Manually verify**

Run: `python run.py` (or `python tools/preview_app.py` if available for a no-camera check), navigate to the Live screen, and confirm the "clean streak" tile renders in the new third grid row without breaking the layout height (checking specifically for the `[[qt-wrapped-label-height]]` failure mode — the tile must not wrap or grow taller than its neighbours).

- [ ] **Step 5: Commit**

```bash
git add src/postureguard/ui/screens/live.py
git commit -m "feat: show clean streak on the Live screen"
```

---

### Task 5: Milestones card on the History screen

**Files:**
- Modify: `src/postureguard/ui/screens/history.py` (constructor signature, `__init__`, `refresh()`)
- Modify: `src/postureguard/app.py` (pass the baseline path when constructing `HistoryScreen`, line 63)

**Interfaces:**
- Consumes: `compute_achievements()` (Task 3), `Baseline.load()` from `src/postureguard/calibration.py`, `paths.baseline_path()` from `src/postureguard/paths.py`.
- Produces: `HistoryScreen(store, baseline_path)` — the constructor now takes a second required argument. `self.milestones_card` attribute.

- [ ] **Step 1: Update imports and the constructor signature**

In `src/postureguard/ui/screens/history.py`, update the import block (lines 1-11):

```python
"""History: how posture has actually gone, rather than how it feels like it went."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from ... import theme
from ...achievements import compute_achievements
from ...calibration import Baseline
from ...rules import FAULT_TITLES
from ...session import SessionStore
from ..charts import Bar, ColumnChart, RankedBarChart
from ..widgets import Card, EmptyState, PageHeader, StatTile, button, label, plain
```

Find the `HistoryScreen.__init__` signature (near line 33-39) and add the new parameter, storing it:

```python
    def __init__(self, store: SessionStore, baseline_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._baseline_path = baseline_path
```

(Keep whatever else the existing `__init__` preamble already does — only the signature and the two new lines are additions; do not remove existing body.)

- [ ] **Step 2: Add the milestones card to the layout**

In `__init__`, immediately after the `charts` grid is built and before `self.set_range(14)` is called (i.e., right after the block ending at line 89 that adds `self.hourly_card`), insert:

```python
        self.milestones_card = Card("Milestones", "A fixed set of things worth noticing.")
        self._milestones_list = QVBoxLayout()
        self._milestones_list.setSpacing(S["sm"])
        self.milestones_card.add(plain(self._milestones_list))
        charts.addWidget(self.milestones_card, 2, 0, 1, 2)
```

- [ ] **Step 3: Populate it in `refresh()`, following the exercises.py rebuild idiom**

Add a new private method to `HistoryScreen`, and call it from `refresh()`. Modify `refresh()` (lines 110-126) to call it unconditionally (milestones are independent of whether there's chart data to show):

```python
    def refresh(self) -> None:
        self._fill_milestones()

        summaries = self.store.daily_summaries(days=self.days)
        tracked_total = sum(s.tracked_seconds for s in summaries)

        has_data = tracked_total > 0
        self.empty.setVisible(not has_data)
        for card in (self.daily_card, self.breakdown_card, self.hourly_card):
            card.setVisible(has_data)
        if not has_data:
            for tile in (self.average_tile, self.best_tile, self.tracked_tile, self.worst_hour_tile):
                tile.set_value("—")
            return

        self._fill_daily(summaries)
        self._fill_breakdown()
        self._fill_hourly()
        self._fill_summary(summaries, tracked_total)

    def _fill_milestones(self) -> None:
        while self._milestones_list.count():
            item = self._milestones_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        baseline = Baseline.load(self._baseline_path)
        for achievement in compute_achievements(self.store, baseline):
            row = label(
                f"{'Earned' if achievement.earned else 'Not yet'} — {achievement.title}",
                "Body",
            )
            row.setToolTip(achievement.description)
            row.setStyleSheet(
                f"color: {theme.IN_TOLERANCE.name()};" if achievement.earned
                else f"color: {theme.MUTED.name()};"
            )
            self._milestones_list.addWidget(row)
```

- [ ] **Step 4: Update `app.py` to pass the baseline path**

In `src/postureguard/app.py`, near line 63:

```python
        self.live = LiveScreen(config.thresholds(), self.store)
        self.history = HistoryScreen(
            self.store, paths.baseline_path(config.calibration_profile)
        )
```

(`paths` is already imported in `app.py` — confirmed by its existing use at line 647.)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -q`
Expected: PASS. No existing test constructs `HistoryScreen` directly (per the earlier exploration, screen construction is exercised manually/visually, not unit-tested), so this is a regression check.

- [ ] **Step 6: Manually verify**

Run: `python run.py`, open Settings and complete calibration (or skip if already calibrated), use the Live screen briefly to log some samples, then open History and confirm:
- The "Milestones" card appears below the existing three chart cards, spanning both columns.
- "Calibrated" shows as earned once calibration has run.
- Labels do not wrap or grow the card taller than expected (again checking `[[qt-wrapped-label-height]]`).

- [ ] **Step 7: Commit**

```bash
git add src/postureguard/ui/screens/history.py src/postureguard/app.py
git commit -m "feat: show milestone achievements on the History screen"
```

---

### Task 6: Weekly trend card on the History screen

**Files:**
- Modify: `src/postureguard/ui/screens/history.py` (`__init__`, `refresh()`)

**Interfaces:**
- Consumes: `compute_weekly_trend()` (Task 2), existing `_duration()` helper (line 18-25), existing `FAULT_TITLES` import.
- Produces: `self.trend_card` attribute.

- [ ] **Step 1: Add the import**

In `src/postureguard/ui/screens/history.py`, add to the import block from Task 5:

```python
from ...weekly_trend import compute_weekly_trend
```

- [ ] **Step 2: Add the trend card to the layout**

In `__init__`, immediately after the milestones card block added in Task 5:

```python
        self.trend_card = Card("This week vs. last week")
        self._trend_label = label("Not enough data yet to compare weeks.", "Body")
        self.trend_card.add(self._trend_label)
        charts.addWidget(self.trend_card, 3, 0, 1, 2)
```

- [ ] **Step 3: Populate it in `refresh()`**

Add a `_fill_trend()` method and call it from `refresh()` alongside `_fill_milestones()`:

```python
    def refresh(self) -> None:
        self._fill_milestones()
        self._fill_trend()

        summaries = self.store.daily_summaries(days=self.days)
        # ... (rest unchanged from Task 5)

    def _fill_trend(self) -> None:
        trend = compute_weekly_trend(self.store)
        if trend is None:
            self._trend_label.setText("Not enough data yet to compare weeks.")
            self._trend_label.setStyleSheet(f"color: {theme.MUTED.name()};")
            return

        delta = trend.this_week_average - trend.last_week_average
        direction = "up" if delta > 0 else "down" if delta < 0 else "unchanged"
        text = f"Average score is {direction} {abs(delta):.0f} points versus last week."
        if trend.most_improved_fault is not None:
            fault_name = FAULT_TITLES.get(trend.most_improved_fault, trend.most_improved_fault.value)
            text += (
                f" {fault_name} time dropped by {_duration(trend.most_improved_seconds)}."
            )
        self._trend_label.setText(text)
        self._trend_label.setStyleSheet(
            f"color: {theme.IN_TOLERANCE.name()};" if delta >= 0
            else f"color: {theme.WARNING.name()};"
        )
```

- [ ] **Step 4: Run the full test suite**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 5: Manually verify**

Run: `python run.py`, open History, confirm the "This week vs. last week" card shows the "not enough data" message on a fresh install, and re-check after seeding a couple of weeks of data via the sqlite file or `tools/preview_app.py` if it supports synthetic history — otherwise confirm the empty-state message renders correctly without layout breakage.

- [ ] **Step 6: Commit**

```bash
git add src/postureguard/ui/screens/history.py
git commit -m "feat: show week-over-week trend on the History screen"
```

---

## Self-Review Notes

- **Spec coverage:** Roadmap items 1 (streak & score — score already existed, streak added), 2 (milestone achievements), and 3 (weekly trend card) are each covered by a task. Score display itself needed no change (`score_tile` already existed on `LiveScreen`).
- **No placeholders:** the draft `test_respects_custom_threshold` placeholder in Task 1 is explicitly replaced with a real assertion in the same task before implementation — flagged inline so the executing agent doesn't skip it.
- **Type consistency:** `Achievement`, `WeeklyTrend` field names are identical everywhere they're constructed (Task 2/3) and consumed (Task 5/6). `HistoryScreen.__init__` signature change (Task 5) is the only breaking interface change, and its one call site (`app.py`) is updated in the same task.
- **Out of scope reminder:** PDF/image export of the weekly trend card (roadmap item 3's "shareable... export") is Phase 3 work (report export), not this plan — this plan only adds the in-app card.
