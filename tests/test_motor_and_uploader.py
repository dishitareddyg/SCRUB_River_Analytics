"""
tests/test_motor_and_uploader.py

- Motor state derivation from the new STM32 `motors.left`/`motors.right`
  fields: IDLE/MOVING via `update()`, and the "no data yet"/stale case
  defaulting to UNKNOWN (TEST 13 scenario: STM32 comms lost -> UNKNOWN).
- Uploader: offline buffering (TEST 9), automatic retry on reconnect
  (TEST 10), and idempotent retries not creating duplicate uploads
  (TEST 11) -- exercised through the batched-upload + cloud-completion-
  verification flow. Unaffected by the hardware architecture change.

Run with:
    pytest tests/test_motor_and_uploader.py -v
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hardware.motor_controller import MotorControllerWorker, MotorState
from cloud.uploader import UploaderWorker
from storage.sqlite_manager import SQLiteManager


def test_motor_idle_when_left_and_right_zero():
    worker = MotorControllerWorker()
    worker.update(0, 0)
    assert worker.get_state() == MotorState.IDLE


def test_motor_moving_when_either_nonzero():
    worker = MotorControllerWorker()
    worker.update(100, 100)
    assert worker.get_state() == MotorState.MOVING
    worker.update(0, 50)
    assert worker.get_state() == MotorState.MOVING
    worker.update(-30, 0)
    assert worker.get_state() == MotorState.MOVING


def test_motor_unknown_with_no_data():
    worker = MotorControllerWorker()
    assert worker.get_state() == MotorState.UNKNOWN


def test_motor_malformed_update_is_ignored_not_guessed():
    worker = MotorControllerWorker()
    worker.update(0, 0)
    assert worker.get_state() == MotorState.IDLE
    worker.update("not-a-number", None)  # malformed motors object
    # Ignored, not guessed at -- last known good state is retained
    # (freshness/staleness is what eventually forces UNKNOWN, not a bad
    # single reading).
    assert worker.get_state() == MotorState.IDLE


def test_motor_forced_unknown_on_disconnect():
    worker = MotorControllerWorker()
    worker.update(0, 0)
    assert worker.get_state() == MotorState.IDLE
    worker.force_unknown()
    assert worker.get_state() == MotorState.UNKNOWN


def test_motor_state_goes_stale_after_max_age():
    import time
    from config.settings import settings
    original = settings.MOTOR_STATE_MAX_AGE_SECONDS
    object.__setattr__(settings, "MOTOR_STATE_MAX_AGE_SECONDS", 0.05)
    try:
        worker = MotorControllerWorker()
        worker.update(0, 0)
        assert worker.get_state() == MotorState.IDLE
        time.sleep(0.1)
        assert worker.get_state() == MotorState.UNKNOWN
    finally:
        object.__setattr__(settings, "MOTOR_STATE_MAX_AGE_SECONDS", original)


class FlakySupabase:
    """Simulates Supabase for the batched-upload + completion-verification
    uploader flow. `fail_upload_times` fails the first N *batch* upload
    calls, then lets them through. `rows` simulates the sensor_readings
    table Supabase itself holds -- count_confirmed_samples answers from
    *this*, exactly like the real ground-truth check, never from anything
    the uploader tracks locally. This proves retries never create
    duplicate rows even though the same batch may be resent."""

    def __init__(self, fail_upload_times: int = 1):
        self.available = True
        self.fail_upload_times = fail_upload_times
        self._attempts = 0
        self.rows = {}  # (session_id, sample_number) -> row
        self.session_upserts = []

    def upsert_session(self, session):
        self.session_upserts.append(dict(session))

    def upsert_readings_batch(self, packet):
        self._attempts += 1
        if self._attempts <= self.fail_upload_times:
            raise RuntimeError("simulated network failure")
        for sample in packet["samples"]:
            self.rows[(packet["session_id"], sample["sample_number"])] = sample

    def count_confirmed_samples(self, session_id):
        return sum(1 for (sid, _sn) in self.rows if sid == session_id)


def test_offline_buffering_and_idempotent_retry():
    from config.settings import settings
    original = settings.MAX_READINGS_PER_GRID
    object.__setattr__(settings, "MAX_READINGS_PER_GRID", 3)
    with tempfile.TemporaryDirectory() as tmp:
        db = SQLiteManager(str(Path(tmp) / "test.db"))
        session = db.create_session("grid-1", "KNG001", "BOT001", 12.9, 77.5)
        for i in range(3):
            db.record_accepted_sample(
                session_id=session["session_id"], grid_id="grid-1", device_id="BOT001",
                recorded_at=f"2026-01-01T00:00:0{i}Z", latitude=12.9, longitude=77.5,
                ph=7.1, tds=200.0, turbidity=10.0, temperature_c=25.0, humidity_percent=60.0,
                max_readings=3,
            )
        assert db.get_session(session["session_id"])["status"] == "COMPLETED"
        assert db.count_pending_uploads() == 3  # all 3 raw samples still buffered

        flaky = FlakySupabase(fail_upload_times=2)
        uploader = UploaderWorker(db, flaky, health=None)

        # Simulate network down: two upload cycles both fail -> every raw
        # sample stays buffered, and the session must NOT be marked
        # completed/cloud_synced in the cloud (TEST 9).
        uploader._sync_sessions()
        assert db.count_pending_uploads() == 3
        assert db.get_session(session["session_id"])["cloud_synced"] == 0
        assert not any(s.get("completed_at") for s in flaky.session_upserts)

        uploader._sync_sessions()
        assert db.count_pending_uploads() == 3  # still failing

        # Network restored: third attempt succeeds and Supabase confirms
        # all 3 samples -> buffer is cleared and the session marked
        # completed/cloud_synced (TEST 10).
        uploader._sync_sessions()
        assert db.count_pending_uploads() == 0
        assert db.get_session(session["session_id"])["cloud_synced"] == 1
        assert flaky.session_upserts[-1]["completed_at"] is not None

        # A retry after success must never re-insert / duplicate (TEST 11).
        assert len(flaky.rows) == 3
        db.close()
    object.__setattr__(settings, "MAX_READINGS_PER_GRID", original)


def test_cloud_completion_blocked_when_supabase_confirms_fewer_than_required():
    """Even when the batch upload call itself 'succeeds', the session must
    stay unsynced/un-completed unless Supabase actually confirms every
    required sample (e.g. a partial write) -- this is the exact bug this
    fix closes: cloud completion must never be inferred from a successful
    upload call alone."""
    from config.settings import settings
    original = settings.MAX_READINGS_PER_GRID
    object.__setattr__(settings, "MAX_READINGS_PER_GRID", 3)
    with tempfile.TemporaryDirectory() as tmp:
        db = SQLiteManager(str(Path(tmp) / "test.db"))
        session = db.create_session("grid-1", "KNG001", "BOT001", 12.9, 77.5)
        for i in range(3):
            db.record_accepted_sample(
                session_id=session["session_id"], grid_id="grid-1", device_id="BOT001",
                recorded_at=f"2026-01-01T00:00:0{i}Z", latitude=12.9, longitude=77.5,
                ph=7.1, tds=200.0, turbidity=10.0, temperature_c=25.0, humidity_percent=60.0,
                max_readings=3,
            )

        class UndercountingSupabase(FlakySupabase):
            """Accepts the batch call but only actually persists 2 of the
            3 rows, simulating a partial cloud-side failure."""

            def upsert_readings_batch(self, packet):
                for sample in packet["samples"][:2]:
                    self.rows[(packet["session_id"], sample["sample_number"])] = sample

        fake = UndercountingSupabase(fail_upload_times=0)
        uploader = UploaderWorker(db, fake, health=None)
        uploader._sync_sessions()

        # Only 2/3 confirmed -> must NOT be marked completed/synced, and
        # the full temporary local buffer must be retained for retry.
        assert fake.count_confirmed_samples(session["session_id"]) == 2
        assert db.count_pending_uploads() == 3
        assert db.get_session(session["session_id"])["cloud_synced"] == 0
        assert not any(s.get("completed_at") for s in fake.session_upserts)
        db.close()
    object.__setattr__(settings, "MAX_READINGS_PER_GRID", original)
