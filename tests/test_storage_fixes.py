"""
tests/test_storage_fixes.py

Targeted regression tests for the three storage/cloud-upload fixes:

  1. SQLite must not permanently retain raw sensor readings -- only a
     temporary offline-upload buffer plus permanent per-session
     averages.
  2. The full accepted-sample write (sample_number, raw reading insert,
     running aggregation, sample_count, completion) is one atomic
     SQLite transaction.
  3. Cloud uploads are batched (one JSON packet per session) and
     idempotent on (session_id, sample_number); the local averages are
     never sent to Supabase, and a session's raw readings are only
     deleted locally once cloud completion is CONFIRMED (every required
     sample verified present in Supabase) -- never merely because an
     upload call returned successfully.

Run with:
    pytest tests/test_storage_fixes.py -v
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from cloud.uploader import UploaderWorker
from storage.buffer_manager import BufferManager
from storage.sqlite_manager import SQLiteManager

GRID_ID = "grid-1"
DEVICE_ID = "BOT001"


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as tmp:
        manager = SQLiteManager(str(Path(tmp) / "test.db"))
        yield manager
        manager.close()


def _accept_sample(db, session_id, **overrides):
    kwargs = dict(
        session_id=session_id, grid_id=GRID_ID, device_id=DEVICE_ID,
        recorded_at="2026-01-01T00:00:00Z", latitude=12.9, longitude=77.5,
        ph=7.1, tds=200.0, turbidity=10.0, temperature_c=25.0, humidity_percent=60.0,
        max_readings=10,
    )
    kwargs.update(overrides)
    return db.record_accepted_sample(**kwargs)


# ---------------------------------------------------------------- Issue 1
def test_raw_reading_removed_after_successful_upload(db):
    """A raw reading must be deleted from SQLite the moment its cloud
    upload is confirmed -- it must not be permanently retained."""
    session = db.create_session(GRID_ID, "G1", DEVICE_ID, 12.9, 77.5)
    _accept_sample(db, session["session_id"])
    assert db.count_pending_uploads() == 1

    buffer = BufferManager(db)
    pending = buffer.get_pending(10)
    assert len(pending) == 1
    buffer.mark_solved(pending[0]["reading_id"])

    assert db.count_pending_uploads() == 0
    assert db.get_readings_for_session(session["session_id"]) == []
    # Confirm there is no other permanent table hiding the raw reading.
    with db._cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM local_readings")
        assert cur.fetchone()["c"] == 0


def test_only_averages_and_metadata_survive_session_completion(db):
    """After a session completes and every reading has been uploaded,
    SQLite must retain only session_id/grid_id/device_id/completion
    timestamp/averages/sample_count -- no raw sensor values."""
    session = db.create_session(GRID_ID, "G1", DEVICE_ID, 12.9, 77.5)
    buffer = BufferManager(db)

    for i in range(10):
        _accept_sample(db, session["session_id"], ph=7.0 + i * 0.01)
        # Simulate the uploader draining the buffer after every sample,
        # as would happen in production with a healthy connection.
        for item in buffer.get_pending(10):
            buffer.mark_solved(item["reading_id"])

    assert db.count_pending_uploads() == 0
    assert db.get_readings_for_session(session["session_id"]) == []

    completed = db.get_session(session["session_id"])
    assert completed["status"] == "COMPLETED"
    assert completed["session_id"] and completed["grid_id"] and completed["device_id"]
    assert completed["completed_at"] is not None

    avg = db.get_local_average(GRID_ID, session["session_id"])
    assert avg is not None
    assert avg["sample_count"] == 10
    assert avg["avg_ph"] == pytest.approx(sum(7.0 + i * 0.01 for i in range(10)) / 10)


def test_offline_reading_stays_buffered_until_upload_succeeds(db):
    """If the cloud is unavailable, the raw reading must remain in the
    temporary buffer (not be discarded, not be "permanently" filed
    away) until an upload actually succeeds."""
    session = db.create_session(GRID_ID, "G1", DEVICE_ID, 12.9, 77.5)
    _accept_sample(db, session["session_id"])
    assert db.count_pending_uploads() == 1
    assert len(db.get_readings_for_session(session["session_id"])) == 1

    buffer = BufferManager(db)
    item = buffer.get_pending(10)[0]
    buffer.mark_failed(item["reading_id"], "network unavailable")

    # Still buffered, not deleted, retry count bumped.
    assert db.count_pending_uploads() == 1
    retried = buffer.get_pending(10)[0]
    assert retried["retry_count"] == 1


def test_invalid_values_stay_null_and_excluded_from_running_average(db):
    session = db.create_session(GRID_ID, "G1", DEVICE_ID, 12.9, 77.5)
    result = None
    for i in range(10):
        result = _accept_sample(db, session["session_id"], ph=None if i % 2 == 0 else 8.0)
    avg = result["averages"]
    assert avg["ph"] == pytest.approx(8.0)  # only the 5 non-null samples count


# ---------------------------------------------------------------- Issue 2
def test_accepted_sample_write_is_a_single_atomic_transaction(db):
    """There must never be a state where sample_count was incremented
    but its reading does not exist, or vice versa. Simulate a crash
    mid-write by forcing the underlying connection to fail partway
    through, and confirm nothing partial was committed."""
    session = db.create_session(GRID_ID, "G1", DEVICE_ID, 12.9, 77.5)

    # Drive the same commit/rollback machinery record_accepted_sample
    # uses (the `_cursor()` context manager), but raise partway through
    # -- after the reading insert and the sample_count bump, before the
    # transaction would commit -- to simulate a crash at that point.
    with pytest.raises(Exception):
        with db._cursor() as cur:
            cur.execute(
                """INSERT INTO local_readings
                   (reading_id, session_id, grid_id, device_id, sample_number, recorded_at,
                    latitude, longitude, ph, tds, turbidity, temperature_c,
                    humidity_percent, created_at, upload_status, retry_count)
                   VALUES ('r1', ?, ?, ?, 1, '2026-01-01T00:00:00Z', 12.9, 77.5,
                           7.0, 200.0, 10.0, 25.0, 60.0, '2026-01-01T00:00:00Z', 'PENDING', 0)""",
                (session["session_id"], GRID_ID, DEVICE_ID),
            )
            cur.execute(
                "UPDATE local_sessions SET sample_count = sample_count + 1 WHERE session_id = ?",
                (session["session_id"],),
            )
            raise RuntimeError("simulated crash before commit")

    # Neither the reading insert nor the sample_count bump may have
    # survived -- the whole transaction must have rolled back together.
    reloaded = db.get_session(session["session_id"])
    assert reloaded["sample_count"] == 0
    assert db.get_readings_for_session(session["session_id"]) == []


def test_no_orphaned_reading_or_orphaned_count_across_many_samples(db):
    """After many accepted samples, sample_count must always equal the
    number of raw readings ever inserted (buffered + already uploaded),
    tracked here via the running aggregation counts."""
    session = db.create_session(GRID_ID, "G1", DEVICE_ID, 12.9, 77.5)
    for _ in range(5):
        _accept_sample(db, session["session_id"])
    reloaded = db.get_session(session["session_id"])
    assert reloaded["sample_count"] == 5
    assert reloaded["count_ph"] == 5
    assert len(db.get_readings_for_session(session["session_id"])) == 5


def test_unique_constraint_on_session_and_sample_number(db):
    session = db.create_session(GRID_ID, "G1", DEVICE_ID, 12.9, 77.5)
    _accept_sample(db, session["session_id"])
    # Directly attempting to insert a duplicate (session_id, sample_number)
    # into the buffer must be rejected by the UNIQUE constraint, as an
    # additional safeguard beyond the transactional sample_number logic.
    with pytest.raises(sqlite3.IntegrityError):
        with db._cursor() as cur:
            cur.execute(
                """INSERT INTO local_readings
                   (reading_id, session_id, grid_id, device_id, sample_number, recorded_at,
                    latitude, longitude, ph, tds, turbidity, temperature_c,
                    humidity_percent, created_at, upload_status, retry_count)
                   VALUES ('dup', ?, ?, ?, 1, '2026-01-01T00:00:00Z', 12.9, 77.5,
                           7.0, 200.0, 10.0, 25.0, 60.0, '2026-01-01T00:00:00Z', 'PENDING', 0)""",
                (session["session_id"], GRID_ID, DEVICE_ID),
            )


# ---------------------------------------------------------------- Issue 3
class RecordingSupabase:
    """Fake Supabase client that records exactly what each call received,
    without a real network/DB dependency. `rows` simulates the actual
    sensor_readings table Supabase holds -- count_confirmed_samples is
    answered from *this*, mirroring the real ground-truth check."""

    def __init__(self):
        self.available = True
        self.session_upserts = []
        self.batch_packets = []
        self.rows = {}

    def upsert_session(self, session):
        self.session_upserts.append(session)

    def upsert_readings_batch(self, packet):
        self.batch_packets.append(packet)
        for sample in packet["samples"]:
            self.rows[(packet["session_id"], sample["sample_number"])] = sample

    def count_confirmed_samples(self, session_id):
        return sum(1 for (sid, _sn) in self.rows if sid == session_id)


def test_cloud_upload_sends_one_batched_packet_of_individual_samples_not_averages(db):
    from config.settings import settings
    # settings is a frozen dataclass singleton -- patch/restore the field
    # directly so the uploader's MAX_READINGS_PER_GRID check matches the
    # small session size used in this test.
    original = settings.MAX_READINGS_PER_GRID
    object.__setattr__(settings, "MAX_READINGS_PER_GRID", 3)

    session = db.create_session(GRID_ID, "G1", DEVICE_ID, 12.9, 77.5)
    for _ in range(3):
        _accept_sample(db, session["session_id"], max_readings=3)
    assert db.get_session(session["session_id"])["status"] == "COMPLETED"

    fake = RecordingSupabase()
    uploader = UploaderWorker(db, fake, health=None)
    uploader._sync_sessions()

    # Exactly one batched packet for the whole session, not one call per sample.
    assert len(fake.batch_packets) == 1
    packet = fake.batch_packets[0]
    assert packet["session_id"] == session["session_id"]
    assert packet["grid_id"] == GRID_ID
    assert packet["device_id"] == DEVICE_ID
    assert len(packet["samples"]) == 3

    for sample in packet["samples"]:
        assert set(sample.keys()) >= {
            "sample_number", "recorded_at", "latitude", "longitude",
            "ph", "tds", "turbidity", "temperature_c", "humidity_percent",
        }
        # The local SQLite averages must never appear in a sample payload.
        assert "avg_ph" not in sample
        assert "sum_ph" not in sample

    # device_id is also carried on the session upsert (matching the
    # existing, unmodified Supabase schema).
    assert fake.session_upserts[0]["device_id"] == DEVICE_ID
    # And the session push that marks completion carries completed_at.
    assert fake.session_upserts[-1]["completed_at"] is not None

    # All 3 samples now confirmed in the cloud -> local buffer purged and
    # the session marked cloud_synced.
    assert fake.count_confirmed_samples(session["session_id"]) == 3
    assert db.count_pending_uploads() == 0
    assert db.get_readings_for_session(session["session_id"]) == []
    assert db.get_session(session["session_id"])["cloud_synced"] == 1
    object.__setattr__(settings, "MAX_READINGS_PER_GRID", original)


def test_cloud_upload_idempotent_retry_no_duplicate(db):
    from config.settings import settings
    original = settings.MAX_READINGS_PER_GRID
    object.__setattr__(settings, "MAX_READINGS_PER_GRID", 1)

    session = db.create_session(GRID_ID, "G1", DEVICE_ID, 12.9, 77.5)
    _accept_sample(db, session["session_id"], max_readings=1)
    assert db.get_session(session["session_id"])["status"] == "COMPLETED"

    class FlakyOnce:
        def __init__(self):
            self.available = True
            self.attempts = 0
            self.rows = {}

        def upsert_session(self, session):
            pass

        def upsert_readings_batch(self, packet):
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("simulated network failure")
            for sample in packet["samples"]:
                self.rows[(packet["session_id"], sample["sample_number"])] = sample

        def count_confirmed_samples(self, session_id):
            return sum(1 for (sid, _sn) in self.rows if sid == session_id)

    flaky = FlakyOnce()
    uploader = UploaderWorker(db, flaky, health=None)
    uploader._sync_sessions()
    assert db.count_pending_uploads() == 1  # first attempt failed, still buffered
    assert db.get_session(session["session_id"])["cloud_synced"] == 0

    uploader._sync_sessions()
    assert db.count_pending_uploads() == 0  # second attempt succeeded and confirmed
    assert db.get_session(session["session_id"])["cloud_synced"] == 1
    assert flaky.attempts == 2
    assert len(flaky.rows) == 1  # idempotent -- no duplicate row
    object.__setattr__(settings, "MAX_READINGS_PER_GRID", original)
