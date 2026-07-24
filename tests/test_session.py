from datetime import date, datetime, timedelta

import pytest

from postureguard.rules import Fault, FaultKind
from postureguard.session import SessionStore

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


class TestPrivacy:
    def test_the_schema_stores_no_image_derived_data(self, store):
        """The privacy promise has to be structurally true, not just intended."""
        columns = {
            row[1] for row in store._db.execute("PRAGMA table_info(samples)").fetchall()
        }
        assert columns == {"ts", "day", "hour", "status", "fault", "severity"}
