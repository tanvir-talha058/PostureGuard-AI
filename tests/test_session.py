from datetime import date, datetime, timedelta

import pytest

from postureguard.rules import Fault, FaultKind
from postureguard.session import SessionStore, STREAK_LOOKBACK_DAYS

TODAY = date(2026, 7, 25)
CRANING = [Fault(FaultKind.FORWARD_HEAD, 2.0, "Pull your chin back.", ())]
TILTING = [Fault(FaultKind.LATERAL_TILT, 1.2, "Level out.", ())]


def at(day: date, hour: int = 10, second: int = 0) -> float:
    """Timestamp `second` seconds into the given hour. Offsets past 59 roll forward."""
    return datetime(day.year, day.month, day.day, hour).timestamp() + second


def fill(store: SessionStore, day: date, hour: int, seconds: int, status: str, faults=()):
    for s in range(seconds):
        store.log(status, faults, when=at(day, hour, s))


@pytest.fixture
def store():
    with SessionStore() as s:
        yield s


class TestLogging:
    def test_writes_at_most_one_row_per_second(self):
        with SessionStore() as store:
            base = at(TODAY)
            written = [store.log("in_tolerance", when=base + i * 0.1) for i in range(30)]
            assert written.count(True) == 3

    def test_records_the_primary_fault_only(self, store):
        fill(store, TODAY, 10, 5, "fault", CRANING + TILTING)
        assert store.fault_breakdown(days=1, today=TODAY) == {FaultKind.FORWARD_HEAD: 5}


class TestScoring:
    def test_score_is_the_share_of_tracked_time_in_tolerance(self, store):
        fill(store, TODAY, 9, 75, "in_tolerance")
        fill(store, TODAY, 10, 25, "fault", CRANING)
        assert store.today(TODAY).score == pytest.approx(75.0)

    def test_time_away_from_the_desk_does_not_count_either_way(self, store):
        """A lunch break is not good posture, and it is not bad posture."""
        fill(store, TODAY, 9, 50, "in_tolerance")
        fill(store, TODAY, 12, 600, "searching")
        summary = store.today(TODAY)
        assert summary.tracked_seconds == 50
        assert summary.score == pytest.approx(100.0)

    def test_a_day_with_no_data_scores_zero_without_dividing_by_zero(self, store):
        assert store.today(TODAY).score == 0.0


class TestDailySummaries:
    def test_returns_one_entry_per_day_requested(self, store):
        assert len(store.daily_summaries(days=14, today=TODAY)) == 14

    def test_days_without_data_come_back_empty_rather_than_missing(self, store):
        """Otherwise a fortnight chart silently compresses the weekend away."""
        fill(store, TODAY, 10, 10, "in_tolerance")
        summaries = store.daily_summaries(days=7, today=TODAY)
        assert summaries[-1].tracked_seconds == 10
        assert all(s.tracked_seconds == 0 for s in summaries[:-1])

    def test_summaries_run_oldest_to_newest(self, store):
        summaries = store.daily_summaries(days=5, today=TODAY)
        assert summaries[-1].day == TODAY
        assert summaries[0].day == TODAY - timedelta(days=4)


class TestBreakdown:
    def test_orders_faults_by_time_spent(self, store):
        fill(store, TODAY, 9, 30, "fault", TILTING)
        fill(store, TODAY, 10, 90, "fault", CRANING)
        assert list(store.fault_breakdown(days=1, today=TODAY)) == [
            FaultKind.FORWARD_HEAD,
            FaultKind.LATERAL_TILT,
        ]

    def test_dominant_fault_is_the_costliest_one(self, store):
        fill(store, TODAY, 9, 30, "fault", TILTING)
        fill(store, TODAY, 10, 90, "fault", CRANING)
        assert store.dominant_fault(days=1, today=TODAY) is FaultKind.FORWARD_HEAD

    def test_no_faults_means_no_dominant_fault(self, store):
        fill(store, TODAY, 10, 20, "in_tolerance")
        assert store.dominant_fault(days=1, today=TODAY) is None

    def test_an_unknown_fault_name_is_skipped_not_fatal(self, store):
        """Reading a database written by a newer version must not crash the app."""
        store._db.execute(
            "INSERT INTO samples (ts, day, hour, status, fault, severity)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (at(TODAY), TODAY.isoformat(), 10, "fault", "quantum_slouch", 1.0),
        )
        store._db.commit()
        assert store.fault_breakdown(days=1, today=TODAY) == {}


class TestHourlyProfile:
    def test_covers_all_twenty_four_hours(self, store):
        assert len(store.hourly_profile(days=1, today=TODAY)) == 24

    def test_locates_the_hour_posture_falls_apart(self, store):
        fill(store, TODAY, 9, 60, "in_tolerance")
        fill(store, TODAY, 15, 60, "fault", CRANING)
        profile = {h.hour: h.score for h in store.hourly_profile(days=1, today=TODAY)}
        assert profile[9] == pytest.approx(100.0)
        assert profile[15] == pytest.approx(0.0)


class TestRetention:
    def test_purges_history_before_a_cutoff(self, store):
        fill(store, TODAY - timedelta(days=40), 10, 10, "in_tolerance")
        fill(store, TODAY, 10, 10, "in_tolerance")
        removed = store.purge_before(TODAY - timedelta(days=30))
        assert removed == 10
        assert store.today(TODAY).tracked_seconds == 10

    def test_purge_older_than_computes_the_cutoff_from_a_window(self, store):
        fill(store, TODAY - timedelta(days=200), 10, 5, "in_tolerance")
        fill(store, TODAY, 10, 5, "in_tolerance")
        removed = store.purge_older_than(180, today=TODAY)
        assert removed == 5
        assert store.today(TODAY).tracked_seconds == 5

    def test_zero_retention_keeps_everything(self, store):
        """Off must never silently mean maximum — the same convention as
        pause_after_idle_minutes elsewhere in the app."""
        fill(store, TODAY - timedelta(days=900), 10, 5, "in_tolerance")
        removed = store.purge_older_than(0, today=TODAY)
        assert removed == 0

    def test_negative_retention_also_keeps_everything(self, store):
        fill(store, TODAY - timedelta(days=900), 10, 5, "in_tolerance")
        assert store.purge_older_than(-5, today=TODAY) == 0


class TestDeleteAll:
    def test_removes_every_row(self, store):
        # Chronological order: `log` rate-limits by wall-clock time, so writing an
        # earlier day after a later one would have the later timestamp block it.
        fill(store, TODAY - timedelta(days=5), 10, 5, "fault", CRANING)
        fill(store, TODAY, 10, 10, "in_tolerance")
        assert store.delete_all() == 15
        assert store.today(TODAY).tracked_seconds == 0
        assert store.daily_summaries(days=14, today=TODAY)[-1].tracked_seconds == 0

    def test_empty_store_removes_nothing(self, store):
        assert store.delete_all() == 0


class TestExportCsv:
    def test_writes_one_row_per_sample_with_a_header(self, store, tmp_path):
        fill(store, TODAY, 9, 3, "in_tolerance")
        fill(store, TODAY, 10, 2, "fault", CRANING)
        out = tmp_path / "history.csv"
        written = store.export_csv(out)
        assert written == 5
        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "timestamp,day,hour,status,fault,severity"
        assert len(lines) == 6  # header + 5 rows

    def test_fault_column_is_the_fault_name_when_present(self, store, tmp_path):
        fill(store, TODAY, 10, 1, "fault", CRANING)
        out = tmp_path / "history.csv"
        store.export_csv(out)
        row = out.read_text(encoding="utf-8").splitlines()[1]
        assert "forward_head" in row

    def test_creates_parent_directories(self, store, tmp_path):
        fill(store, TODAY, 10, 1, "in_tolerance")
        out = tmp_path / "nested" / "history.csv"
        assert store.export_csv(out) == 1
        assert out.exists()

    def test_empty_store_writes_header_only(self, store, tmp_path):
        out = tmp_path / "history.csv"
        assert store.export_csv(out) == 0
        assert len(out.read_text(encoding="utf-8").splitlines()) == 1


class TestSchemaVersioning:
    def test_a_fresh_database_is_stamped_with_the_current_version(self, store):
        from postureguard.session import SCHEMA_VERSION

        version = store._db.execute("PRAGMA user_version").fetchone()[0]
        assert version == SCHEMA_VERSION

    def test_a_pre_versioning_database_is_upgraded_in_place(self, tmp_path):
        """A database that predates this feature reads back as user_version 0 —
        SQLite's own default — and must not be mistaken for a broken one."""
        import sqlite3

        from postureguard.session import SCHEMA, SCHEMA_VERSION

        path = tmp_path / "legacy.db"
        raw = sqlite3.connect(str(path))
        raw.executescript(SCHEMA)  # the table exists, but user_version was never set
        raw.commit()
        raw.close()

        with SessionStore(path) as store:
            version = store._db.execute("PRAGMA user_version").fetchone()[0]
            assert version == SCHEMA_VERSION
            # Existing data must survive the upgrade untouched.
            store.log("in_tolerance", when=at(TODAY, 10, 0))
            assert store.today(TODAY).tracked_seconds == 1

    def test_reopening_an_up_to_date_database_is_a_no_op(self, tmp_path):
        path = tmp_path / "sessions.db"
        with SessionStore(path) as store:
            store.log("in_tolerance", when=at(TODAY, 10, 0))
        with SessionStore(path) as reopened:
            assert reopened.today(TODAY).tracked_seconds == 1


class TestPrivacy:
    def test_the_schema_stores_no_image_derived_data(self, store):
        """The privacy promise has to be structurally true, not just intended."""
        columns = {
            row[1] for row in store._db.execute("PRAGMA table_info(samples)").fetchall()
        }
        assert columns == {"ts", "day", "hour", "status", "fault", "severity"}


class TestStreaks:
    def test_zero_when_no_history(self, store):
        assert store.current_streak(today=TODAY) == 0

    def test_counts_consecutive_clean_days_ending_today(self, store):
        # Fill in chronological order (oldest first) to avoid rate limiter blocks
        for offset in range(2, -1, -1):
            day = TODAY - timedelta(days=offset)
            fill(store, day, 9, 1800, "in_tolerance")
        assert store.current_streak(today=TODAY) == 3

    def test_a_bad_day_breaks_the_streak(self, store):
        # Fill in chronological order (oldest first)
        fill(store, TODAY - timedelta(days=2), 9, 1800, "in_tolerance")
        fill(store, TODAY - timedelta(days=1), 9, 1800, "fault", CRANING)
        fill(store, TODAY, 9, 1800, "in_tolerance")
        assert store.current_streak(today=TODAY) == 1

    def test_a_day_with_too_little_tracked_time_is_skipped_not_broken(self, store):
        # Today has nothing logged yet (session hasn't started) — should not zero the streak.
        # Fill in chronological order (oldest first)
        fill(store, TODAY - timedelta(days=2), 9, 1800, "in_tolerance")
        fill(store, TODAY - timedelta(days=1), 9, 1800, "in_tolerance")
        assert store.current_streak(today=TODAY) == 2

    def test_respects_custom_threshold(self, store):
        # 900s in_tolerance, 900s fault -> 50% score. Below the default 80% threshold
        # but above a relaxed 40% threshold.
        fill(store, TODAY, 9, 900, "in_tolerance")
        fill(store, TODAY, 10, 900, "fault", CRANING)
        assert store.current_streak(today=TODAY) == 0
        assert store.current_streak(threshold=40.0, today=TODAY) == 1

    def test_streak_is_bounded_by_lookback_days(self, store):
        # A true streak longer than STREAK_LOOKBACK_DAYS is reported as exactly that many.
        # Fill STREAK_LOOKBACK_DAYS + 1 consecutive clean days.
        for offset in range(STREAK_LOOKBACK_DAYS, -1, -1):
            day = TODAY - timedelta(days=offset)
            fill(store, day, 9, 1800, "in_tolerance")
        assert store.current_streak(today=TODAY) == STREAK_LOOKBACK_DAYS


class TestFaultRange:
    def test_empty_range_returns_empty_dict(self, store):
        assert store.fault_seconds_in_range(TODAY, TODAY) == {}

    def test_counts_only_within_the_bounds(self, store):
        # Fill in chronological order (oldest first)
        fill(store, TODAY - timedelta(days=10), 9, 60, "fault", CRANING)
        fill(store, TODAY - timedelta(days=1), 9, 30, "fault", TILTING)
        result = store.fault_seconds_in_range(TODAY - timedelta(days=6), TODAY)
        assert result == {FaultKind.LATERAL_TILT: 30}

    def test_most_costly_first(self, store):
        fill(store, TODAY, 9, 10, "fault", TILTING)
        fill(store, TODAY, 10, 40, "fault", CRANING)
        result = store.fault_seconds_in_range(TODAY, TODAY)
        assert list(result.keys()) == [FaultKind.FORWARD_HEAD, FaultKind.LATERAL_TILT]
