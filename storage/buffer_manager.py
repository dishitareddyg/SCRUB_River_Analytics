"""
storage/buffer_manager.py

Thin, explicit wrapper around the SQLite local_readings table used as a
TEMPORARY offline upload buffer. Kept as its own module (per the
requested project layout) so the cloud uploader depends on a small,
clearly-named interface rather than reaching into SQLiteManager's full
surface directly.

Buffer lifecycle:
  - A record enters the buffer the instant a reading is accepted, as
    part of the single atomic transaction performed by
    SQLiteManager.record_accepted_sample (so an accepted reading can
    never exist without a corresponding buffer entry, and sample_count
    can never be incremented without it).
  - A session's records are kept in the buffer, ALL together, until
    that session's cloud completion is confirmed -- i.e. Supabase
    itself reports every required sample present (see
    UploaderWorker._complete_session_in_cloud). Only then are they
    permanently deleted, all at once (SQLiteManager.delete_session_readings).
    An individual sample's upload succeeding is not, by itself, reason
    to delete anything -- deletion is always gated on the whole
    session's cloud completion.
  - mark_solved/mark_failed remain as low-level per-reading status
    primitives (e.g. for tests/tooling exercising a single buffered
    row); the production upload path no longer deletes a reading as a
    side effect of its own individual upload succeeding.
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
