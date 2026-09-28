"""
measurement/session_manager.py — verbatim from SCRUB_River_Analytics.

At most one ACTIVE session per grid at a time.  ACTIVE sessions are reused
until MAX_READINGS_PER_GRID; only then does the next accepted sample create
a new session.
"""

from __future__ import annotations

from monitoring.logger import get_logger
from storage.sqlite_manager import SQLiteManager

logger = get_logger(__name__)


class SessionManager:
    def __init__(self, sqlite_manager: SQLiteManager) -> None:
        self._db = sqlite_manager

    def get_or_create_active_session(
        self, grid: dict, device_id: str, latitude: float, longitude: float
    ) -> dict:
        existing = self._db.get_active_session(grid["grid_id"])
        if existing is not None:
            return existing
        session = self._db.create_session(
            grid_id=grid["grid_id"],
            grid_code=grid.get("grid_code", ""),
            device_id=device_id,
            latitude=latitude,
            longitude=longitude,
        )
        return session
