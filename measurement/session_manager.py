"""
measurement/session_manager.py

Implements the measurement-session lifecycle (spec sections 17-20, 39-40):

  - A grid can have many sessions over its lifetime, but at most one
    ACTIVE session at a time.
  - An ACTIVE session is reused for every accepted sample until it
    reaches MAX_READINGS_PER_GRID, at which point it is marked
    COMPLETED and becomes immutable.
  - A later visit to the same grid (whether the bot left the radius or
    not) NEVER creates a new session while the current one is still
    ACTIVE and has capacity -- it simply keeps using it. GPS jitter
    around the radius boundary therefore cannot fragment one visit into
    multiple sessions, because sessions are keyed on grid + ACTIVE
    status, not on "GPS just (re)entered the radius".
  - Only once a session is COMPLETED does the next accepted sample for
    that grid create a brand-new session (new UUID, sample_number
    restarting at 1).
"""

from __future__ import annotations

from monitoring.logger import get_logger
from storage.sqlite_manager import SQLiteManager

logger = get_logger(__name__)


class SessionManager:
    def __init__(self, sqlite_manager: SQLiteManager):
        self._db = sqlite_manager

    def get_or_create_active_session(self, grid: dict, device_id: str,
                                      latitude: float, longitude: float) -> dict:
        existing = self._db.get_active_session(grid["grid_id"])
        if existing is not None:
            # An ACTIVE session, by construction, never has sample_count
            # >= MAX_READINGS_PER_GRID (it is flipped to COMPLETED the
            # instant that happens -- see SQLiteManager.record_accepted_sample).
            return existing

        session = self._db.create_session(
            grid_id=grid["grid_id"],
            grid_code=grid.get("grid_code", ""),
            device_id=device_id,
            latitude=latitude,
            longitude=longitude,
        )
        return session

    # NOTE: recording an accepted sample (inserting the raw reading,
    # updating the running sum/count aggregation, bumping sample_count,
    # and completing the session) all happens in ONE atomic SQLite
    # transaction -- see SQLiteManager.record_accepted_sample(), called
    # directly by MeasurementManager. That keeps every one of those
    # writes atomic, which splitting them across two manager calls (as
    # this class previously did) could not guarantee.
