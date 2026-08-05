"""Session history in SQLite.

**What is stored:** one row per second holding a status, an optional fault name, and a
severity number. **What is never stored:** anything derived from the image itself — no
frames, no thumbnails, no landmark coordinates. The privacy promise is only worth
making if the storage layer makes it structurally true, so this module has no access to
imagery at all.

One row per second rather than per frame keeps a full working day at roughly 30k rows,
which SQLite aggregates without breaking a sweat.
"""

from __future__ import annotations

import csv
import sqlite3
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .rules import Fault, FaultKind

SCHEMA = """
CREATE TABLE IF NOT EXISTS samples (
    ts       REAL NOT NULL,
    day      TEXT NOT NULL,
    hour     INTEGER NOT NULL,
    status   TEXT NOT NULL,
    fault    TEXT,
    severity REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_samples_day ON samples(day);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);
"""

#: Bumped whenever SCHEMA changes. Stamped into the database itself via
#: `PRAGMA user_version`, so a future column or index change has somewhere to land —
#: `_migrate` can branch on the version it finds and step forward — instead of every
#: existing install breaking the moment the schema moves.
SCHEMA_VERSION = 1

#: Statuses that count as the user actually being at the desk and measurable. Time
#: spent away must not dilute the score — a lunch break is not good posture.
PRESENT_STATUSES = frozenset({"in_tolerance", "drifting", "fault"})

#: Practical ceiling on how far back current_streak() computes. Not a real product
#: limit expected to bind for typical usage.
STREAK_LOOKBACK_DAYS = 60


@dataclass(frozen=True)
class DaySummary:
    day: date
    tracked_seconds: int
    in_tolerance_seconds: int

    @property
    def score(self) -> float:
        """Share of tracked time spent within tolerance, 0-100."""
        if self.tracked_seconds == 0:
            return 0.0
        return 100.0 * self.in_tolerance_seconds / self.tracked_seconds


@dataclass(frozen=True)
class HourSummary:
    hour: int
    tracked_seconds: int
    in_tolerance_seconds: int

    @property
    def score(self) -> float:
        if self.tracked_seconds == 0:
            return 0.0
        return 100.0 * self.in_tolerance_seconds / self.tracked_seconds


class SessionStore:
    """Append-only log of posture status, plus the aggregates the History screen needs."""

    def __init__(self, path: Path | str = ":memory:") -> None:
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # The UI thread and the frame timer both touch this; Qt marshals them onto the
        # same thread, but check_same_thread stays off so a future worker cannot
        # deadlock on it silently.
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._migrate()
        self._last_logged = 0.0

    def _migrate(self) -> None:
        """Bring the database up to SCHEMA_VERSION.

        `CREATE ... IF NOT EXISTS` makes running SCHEMA idempotent, so this is safe to
        call against a brand-new file, a database from before versioning existed
        (reads back as version 0, SQLite's default), or one already current — all
        three converge on the same state. A real future migration adds a branch keyed
        on the version found, each one stepping `user_version` forward by exactly one
        so a database can hop through several releases in sequence.
        """
        self._db.executescript(SCHEMA)
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version < SCHEMA_VERSION:
            self._db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._db.commit()

    # --- writing ------------------------------------------------------------------

    def log(
        self,
        status: str,
        faults: Sequence[Fault] = (),
        when: float | None = None,
    ) -> bool:
        """Record one second of state. Returns True if a row was actually written.

        Called every frame; writes at most once per second. Keeping the rate limit
        here rather than in the caller means every call site gets it for free.
        """
        now = time.time() if when is None else when
        if now - self._last_logged < 1.0:
            return False
        self._last_logged = now

        stamp = datetime.fromtimestamp(now)
        primary = faults[0] if faults else None
        self._db.execute(
            "INSERT INTO samples (ts, day, hour, status, fault, severity)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                now,
                stamp.date().isoformat(),
                stamp.hour,
                status,
                primary.kind.value if primary else None,
                primary.severity if primary else 0.0,
            ),
        )
        self._db.commit()
        return True

    # --- reading ------------------------------------------------------------------

    def daily_summaries(self, days: int = 14, today: date | None = None) -> list[DaySummary]:
        """One entry per day, most recent last, including days with no data.

        Gaps are returned as zero-second days rather than omitted, so a chart of the
        last fortnight shows the weekend as empty instead of quietly compressing it.
        """
        end = today or date.today()
        start = end - timedelta(days=days - 1)
        rows = self._db.execute(
            "SELECT day,"
            "       COUNT(*) FILTER (WHERE status IN ('in_tolerance','drifting','fault')),"
            "       COUNT(*) FILTER (WHERE status = 'in_tolerance')"
            " FROM samples WHERE day >= ? GROUP BY day",
            (start.isoformat(),),
        ).fetchall()
        by_day = {row[0]: (row[1], row[2]) for row in rows}

        summaries = []
        for offset in range(days):
            current = start + timedelta(days=offset)
            tracked, good = by_day.get(current.isoformat(), (0, 0))
            summaries.append(DaySummary(current, tracked, good))
        return summaries

    def fault_breakdown(self, days: int = 7, today: date | None = None) -> dict[FaultKind, int]:
        """Seconds attributed to each fault type, most costly first."""
        end = today or date.today()
        start = end - timedelta(days=days - 1)
        rows = self._db.execute(
            "SELECT fault, COUNT(*) FROM samples"
            " WHERE day >= ? AND fault IS NOT NULL GROUP BY fault",
            (start.isoformat(),),
        ).fetchall()
        counted = Counter()
        for name, count in rows:
            try:
                counted[FaultKind(name)] = count
            except ValueError:
                continue  # a fault kind from a newer version; ignore rather than crash
        return dict(counted.most_common())

    def hourly_profile(self, days: int = 7, today: date | None = None) -> list[HourSummary]:
        """Score by hour of day — shows when posture reliably falls apart."""
        end = today or date.today()
        start = end - timedelta(days=days - 1)
        rows = self._db.execute(
            "SELECT hour,"
            "       COUNT(*) FILTER (WHERE status IN ('in_tolerance','drifting','fault')),"
            "       COUNT(*) FILTER (WHERE status = 'in_tolerance')"
            " FROM samples WHERE day >= ? GROUP BY hour",
            (start.isoformat(),),
        ).fetchall()
        by_hour = {row[0]: (row[1], row[2]) for row in rows}
        return [
            HourSummary(hour, *by_hour.get(hour, (0, 0)))
            for hour in range(24)
        ]

    def today(self, today: date | None = None) -> DaySummary:
        current = today or date.today()
        row = self._db.execute(
            "SELECT COUNT(*) FILTER (WHERE status IN ('in_tolerance','drifting','fault')),"
            "       COUNT(*) FILTER (WHERE status = 'in_tolerance')"
            " FROM samples WHERE day = ?",
            (current.isoformat(),),
        ).fetchone()
        return DaySummary(current, row[0] or 0, row[1] or 0)

    def dominant_fault(self, days: int = 7, today: date | None = None) -> FaultKind | None:
        """The fault worth building a stretch routine around."""
        breakdown = self.fault_breakdown(days, today)
        return next(iter(breakdown), None)

    def recent_scores(self, days: int = 14, today: date | None = None) -> list[float]:
        return [summary.score for summary in self.daily_summaries(days, today)]

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
        Streaks longer than `STREAK_LOOKBACK_DAYS` days are reported as exactly that many.
        """
        summaries = list(reversed(self.daily_summaries(days=STREAK_LOOKBACK_DAYS, today=today)))
        streak = 0
        for summary in summaries:
            if summary.tracked_seconds < min_tracked_seconds:
                continue
            if summary.score < threshold:
                break
            streak += 1
        return streak

    def has_ever_had_a_clean_day(
        self,
        threshold: float = 80.0,
        min_tracked_seconds: int = 1800,
        days: int = 365,
        today: date | None = None,
    ) -> bool:
        """Whether any day in the last `days` days cleared `threshold` with enough
        tracked time behind it — a yes/no question the `first_clean_day` achievement
        needs answered without materializing a year of `DaySummary` objects just to
        scan them in Python.
        """
        end = today or date.today()
        start = end - timedelta(days=days - 1)
        row = self._db.execute(
            "SELECT 1 FROM samples WHERE day >= ? AND day <= ?"
            " GROUP BY day"
            " HAVING COUNT(*) FILTER (WHERE status IN ('in_tolerance','drifting','fault'))"
            "        >= ?"
            "    AND (100.0 * COUNT(*) FILTER (WHERE status = 'in_tolerance')"
            "         / NULLIF(COUNT(*) FILTER (WHERE status IN ('in_tolerance','drifting','fault')), 0))"
            "        >= ?"
            " LIMIT 1",
            (start.isoformat(), end.isoformat(), min_tracked_seconds, threshold),
        ).fetchone()
        return row is not None

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

    def purge_before(self, cutoff: date) -> int:
        """Delete history older than a date. Returns rows removed."""
        cursor = self._db.execute("DELETE FROM samples WHERE day < ?", (cutoff.isoformat(),))
        self._db.commit()
        return cursor.rowcount

    def delete_all(self) -> int:
        """Erase every stored sample. Returns rows removed.

        For the user who wants to walk away with nothing left behind — the privacy
        promise this app makes is only real if there is a door, not just a retention
        timer that eventually gets around to it.
        """
        cursor = self._db.execute("DELETE FROM samples")
        self._db.commit()
        return cursor.rowcount

    # --- export ---------------------------------------------------------------

    def export_csv(self, path: Path) -> int:
        """Write every stored sample to a CSV file. Returns rows written.

        The same columns the schema holds and nothing more — one status, one
        optional fault name, one severity number per second. There is no image data
        to leave out, but the export mirroring the schema exactly is itself part of
        the privacy story: what you get is provably everything, not a curated subset.
        """
        rows = self._db.execute(
            "SELECT ts, day, hour, status, fault, severity FROM samples ORDER BY ts"
        ).fetchall()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["timestamp", "day", "hour", "status", "fault", "severity"])
            for ts, day, hour, status, fault, severity in rows:
                writer.writerow([
                    datetime.fromtimestamp(ts).isoformat(timespec="seconds"),
                    day, hour, status, fault or "", severity,
                ])
        return len(rows)

    def purge_older_than(self, days: int, today: date | None = None) -> int:
        """Delete rows more than `days` days old. `days <= 0` keeps everything.

        The convenience most callers actually want: a retention *window*, not a
        calendar cutoff. Zero-or-negative disabling rather than deleting everything
        matches the same convention `pause_after_idle_minutes` uses elsewhere in
        the app — a setting reading as "off" should never read as "maximum".
        """
        if days <= 0:
            return 0
        cutoff = (today or date.today()) - timedelta(days=days)
        return self.purge_before(cutoff)

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> SessionStore:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
