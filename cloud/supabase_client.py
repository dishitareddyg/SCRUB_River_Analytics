"""
cloud/supabase_client.py

Client wrapper for Supabase REST API.
Handles:
  - Fetching grid definitions from `grids` table.
  - Fetching pending missions from `missions` & `mission_grids`.
  - Updating mission and mission_grid progress statuses.
  - Upserting sessions to `grid_sessions` (with fallback to `measurement_sessions`).
  - Batch upserting sensor samples to `sensor_samples` (with fallback to `sensor_readings`).
  - Verifying sample counts in the cloud.
"""

from __future__ import annotations

from typing import List, Optional

try:
    from supabase import Client, create_client
except ImportError:
    Client = object
    create_client = None

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
            logger.warning("SUPABASE_URL/SUPABASE_KEY not configured — cloud disabled")

    @property
    def available(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------
    # Grids
    # ------------------------------------------------------------------
    def fetch_grids(self) -> list[dict]:
        """Fetch all grid definitions from Supabase."""
        if not self._client:
            return []
        try:
            resp = (
                self._client.table("grids")
                .select("grid_id, lake_id, grid_code, grid_size_m, center_lat, center_lon")
                .execute()
            )
            return resp.data or []
        except Exception as exc:
            logger.warning("Error fetching grids from Supabase: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Autonomous Missions
    # ------------------------------------------------------------------
    def fetch_pending_mission(self, device_id: str) -> Optional[dict]:
        """Fetch the oldest PENDING mission assigned to this device."""
        if not self._client:
            return None
        try:
            resp = (
                self._client.table("missions")
                .select("mission_id, lake_id, status, created_at")
                .eq("device_id", device_id)
                .eq("status", "PENDING")
                .order("created_at", desc=False)
                .limit(1)
                .execute()
            )
            if resp.data:
                return resp.data[0]
        except Exception as exc:
            logger.debug("Missions table query: %s", exc)
        return None

    def fetch_mission_waypoints(self, mission_id: str) -> List[dict]:
        """
        Fetch ordered list of grid points for a mission from mission_grids + grids.
        Returns: [{"grid_id": ..., "lat": ..., "lon": ..., "grid_code": ..., "sequence_order": ...}, ...]
        """
        if not self._client:
            return []
        try:
            # Query mission_grids joined with grids
            resp = (
                self._client.table("mission_grids")
                .select("grid_id, sequence_order, status, grids(grid_code, center_lat, center_lon)")
                .eq("mission_id", mission_id)
                .order("sequence_order", desc=False)
                .execute()
            )
            waypoints = []
            for item in (resp.data or []):
                grid_info = item.get("grids") or {}
                waypoints.append({
                    "grid_id": item["grid_id"],
                    "lat": float(grid_info.get("center_lat", 0.0)),
                    "lon": float(grid_info.get("center_lon", 0.0)),
                    "grid_code": grid_info.get("grid_code", ""),
                    "sequence_order": item.get("sequence_order", 0),
                })
            return waypoints
        except Exception as exc:
            logger.warning("Error fetching mission waypoints: %s", exc)
            return []

    def mark_mission_active(self, mission_id: str) -> None:
        if not self._client:
            return
        import time
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._client.table("missions").update({
            "status": "ACTIVE",
            "started_at": now
        }).eq("mission_id", mission_id).execute()

    def mark_mission_complete(self, mission_id: str) -> None:
        if not self._client:
            return
        import time
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._client.table("missions").update({
            "status": "COMPLETED",
            "completed_at": now
        }).eq("mission_id", mission_id).execute()

    def mark_mission_aborted(self, mission_id: str, reason: str = "") -> None:
        if not self._client:
            return
        import time
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._client.table("missions").update({
            "status": "ABORTED",
            "completed_at": now,
            "notes": f"Aborted: {reason}"
        }).eq("mission_id", mission_id).execute()

    def mark_mission_grid_navigating(self, mission_id: str, grid_id: str) -> None:
        if not self._client:
            return
        self._client.table("mission_grids").update({
            "status": "NAVIGATING"
        }).eq("mission_id", mission_id).eq("grid_id", grid_id).execute()

    def mark_mission_grid_completed(self, mission_id: str, grid_id: str, session_id: str) -> None:
        if not self._client:
            return
        self._client.table("mission_grids").update({
            "status": "COMPLETED",
            "session_id": session_id
        }).eq("mission_id", mission_id).eq("grid_id", grid_id).execute()

    # ------------------------------------------------------------------
    # Sessions (grid_sessions / measurement_sessions)
    # ------------------------------------------------------------------
    def upsert_session(self, session: dict) -> None:
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

        # Try grid_sessions first (matching current DB schema), fallback to measurement_sessions
        try:
            self._client.table("grid_sessions").upsert(payload, on_conflict="session_id").execute()
        except Exception:
            self._client.table("measurement_sessions").upsert(payload, on_conflict="session_id").execute()

    # ------------------------------------------------------------------
    # Readings (sensor_samples / sensor_readings)
    # ------------------------------------------------------------------
    def upsert_readings_batch(self, packet: dict) -> None:
        if not self._client:
            raise RuntimeError("Supabase client not configured")

        session_id = packet["session_id"]
        grid_id = packet["grid_id"]
        rows = [
            {
                "sample_id": sample.get("reading_id"),  # sample_id in sensor_samples
                "reading_id": sample.get("reading_id"), # fallback for sensor_readings
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

        try:
            # Matches uploaded schema: sensor_samples
            clean_rows = [{k: v for k, v in r.items() if k != "reading_id"} for r in rows]
            self._client.table("sensor_samples").upsert(
                clean_rows, on_conflict="session_id,sample_number"
            ).execute()
        except Exception:
            # Fallback to sensor_readings
            clean_rows = [{k: v for k, v in r.items() if k != "sample_id"} for r in rows]
            self._client.table("sensor_readings").upsert(
                clean_rows, on_conflict="session_id,sample_number"
            ).execute()

    def count_confirmed_samples(self, session_id: str) -> int:
        if not self._client:
            raise RuntimeError("Supabase client not configured")

        for table in ("sensor_samples", "sensor_readings"):
            try:
                resp = (
                    self._client.table(table)
                    .select("sample_number", count="exact")
                    .eq("session_id", session_id)
                    .execute()
                )
                if resp.count is not None:
                    return resp.count
                if resp.data is not None:
                    return len(resp.data)
            except Exception:
                continue
        return 0
