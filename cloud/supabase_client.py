"""
cloud/supabase_client.py

Thin wrapper around the official `supabase-py` client. Centralizes
Supabase configuration/access so no other module builds its own client
or embeds a URL/key.

Responsibilities:
  - Fetch grid definitions (grids table) for grid synchronization
    (spec section 7 -- grids are NEVER hardcoded in this project).
  - Upsert measurement_sessions rows for cloud persistence, using
    idempotent upserts keyed on the existing session_id PK.
  - Upload a session's pending raw samples as ONE batched request
    (upsert_readings_batch), idempotent on the existing UNIQUE
    (session_id, sample_number) constraint -- retries never create
    duplicate sensor_readings rows.
  - Report back, as ground truth, exactly how many samples Supabase
    itself currently has for a given session (count_confirmed_samples).
    This is the only source of truth the uploader is allowed to use to
    decide whether a session's cloud upload is actually complete --
    never the local SQLite buffer/count.
"""

from __future__ import annotations

from typing import Optional

from supabase import Client, create_client

from config.settings import settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


class SupabaseClientWrapper:
    def __init__(self):
        self._client: Optional[Client] = None
        if settings.SUPABASE_URL and settings.SUPABASE_KEY:
            try:
                self._client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
                logger.info("Supabase client initialized")
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to initialize Supabase client: %s", exc)
                self._client = None
        else:
            logger.warning("SUPABASE_URL/SUPABASE_KEY not configured -- cloud features disabled")

    @property
    def available(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------
    def fetch_grids(self) -> list[dict]:
        """Fetch the current grid definitions for grid matching (never
        hardcoded, per spec section 7)."""
        if not self._client:
            return []
        resp = (
            self._client.table("grids")
            .select("grid_id, lake_id, grid_code, grid_size_m, center_lat, center_lon")
            .execute()
        )
        return resp.data or []

    def upsert_session(self, session: dict) -> None:
        """Idempotent upsert keyed on session_id PK -- safe to call
        repeatedly (e.g. on creation, and again on completion)."""
        if not self._client:
            raise RuntimeError("Supabase client not configured")

        payload = {
            "session_id": session["session_id"],
            "grid_id": session["grid_id"],
            "device_id": session["device_id"],
            "started_at": session["started_at"],
            "completed_at": session.get("completed_at"),
            "latitude": session.get("latitude"),
            "longitude": session.get("longitude"),
            "sample_count": session["sample_count"],
        }
        self._client.table("measurement_sessions").upsert(payload, on_conflict="session_id").execute()

    def upsert_readings_batch(self, packet: dict) -> None:
        """Upload every sample in one batched cloud packet as a SINGLE
        request. `packet` is the transport-format dict:
            {"session_id", "grid_id", "device_id", "samples": [...]}
        The packet is only the transport format -- each sample is still
        stored as its own row in `sensor_readings`. The batch upsert is
        keyed on the existing UNIQUE(session_id, sample_number)
        constraint, so retrying an already-partially-applied batch (or
        the same batch twice) can never create duplicate rows. Each
        sample also carries its client-generated reading_id (the
        existing PK) for the same reason.
        """
        if not self._client:
            raise RuntimeError("Supabase client not configured")

        session_id = packet["session_id"]
        grid_id = packet["grid_id"]
        rows = [
            {
                "reading_id": sample["reading_id"],
                "session_id": session_id,
                "grid_id": grid_id,
                "sample_number": sample["sample_number"],
                "recorded_at": sample["recorded_at"],
                "latitude": sample.get("latitude"),
                "longitude": sample.get("longitude"),
                "ph": sample.get("ph"),
                "tds": sample.get("tds"),
                "turbidity": sample.get("turbidity"),
                "temperature_c": sample.get("temperature_c"),
                "humidity_percent": sample.get("humidity_percent"),
            }
            for sample in packet["samples"]
        ]
        if not rows:
            return

        self._client.table("sensor_readings").upsert(
            rows, on_conflict="session_id,sample_number"
        ).execute()

    def count_confirmed_samples(self, session_id: str) -> int:
        """Ground truth used to gate cloud completion: how many
        sensor_readings rows Supabase itself currently has for this
        session. NEVER inferred from the local SQLite buffer -- the
        buffer only tells us what *might* still need uploading, not
        what Supabase has actually persisted and confirmed."""
        if not self._client:
            raise RuntimeError("Supabase client not configured")

        resp = (
            self._client.table("sensor_readings")
            .select("sample_number", count="exact")
            .eq("session_id", session_id)
            .execute()
        )
        if resp.count is not None:
            return resp.count
        return len(resp.data or [])
