"""
storage/buffer_manager.py

Thin wrapper around SQLite local_readings table for offline upload buffering.
"""

from __future__ import annotations

from storage.sqlite_manager import SQLiteManager


class BufferManager:
    def __init__(self, sqlite_manager: SQLiteManager):
        self._db = sqlite_manager

    def get_pending(self, limit: int) -> list[dict]:
        return self._db.get_pending_uploads(limit)

    def mark_solved(self, reading_id: str) -> None:
        self._db.mark_upload_succeeded(reading_id)

    def mark_failed(self, reading_id: str, error: str) -> None:
        self._db.mark_upload_failed(reading_id, error)

    def pending_count(self) -> int:
        return self._db.count_pending_uploads()
