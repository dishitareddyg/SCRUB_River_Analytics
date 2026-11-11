"""
cloud/supabase_client.py

Thin Supabase (PostgREST) wrapper.  Never used by navigation.

  * upsert_sensor_reading  — ONE record, idempotent on local_record_id
  * upsert_mission         — mission metadata / status / progress
  * upsert_waypoints       — ordered waypoints (UNIQUE mission_id, sequence_order)
  * is_reachable           — cheap TCP connectivity probe

Geometry columns (PostGIS, SRID 4326) are sent as EWKT strings, which
PostgREST casts to geometry:  "SRID=4326;POINT(lon lat)".
"""

from __future__ import annotations

import socket
from typing import Optional
from urllib.parse import urlparse

try:
    from supabase import create_client
except ImportError:  # pragma: no cover
    create_client = None

try:
    from supabase.client import ClientOptions
except ImportError:  # pragma: no cover
    ClientOptions = None

from config.settings import settings
from monitoring.logger import get_logger
from navigation.geometry import point_to_ewkt, polygon_to_ewkt

logger = get_logger(__name__)

SENSOR_FIELDS = ("ph", "tds", "turbidity", "temperature_c", "humidity_percent")


class CloudError(RuntimeError):
    pass


class SupabaseClientWrapper:
    def __init__(self, client=None):
        self._client = client
        if self._client is not None:
            return
        if not (settings.SUPABASE_URL and settings.SUPABASE_KEY):
            logger.warning("SUPABASE_URL/SUPABASE_KEY not configured — cloud sync disabled")
            return
        if create_client is None:
            logger.error("supabase package not installed — cloud sync disabled")
            return
        try:
            if ClientOptions is not None:
                opts = ClientOptions(postgrest_client_timeout=settings.SUPABASE_TIMEOUT_S)
                self._client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY, options=opts)
            else:
                self._client = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
            logger.info("Supabase client initialized")
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to initialize Supabase client: %s", exc)
            self._client = None

    @property
    def available(self) -> bool:
        return self._client is not None

    def is_reachable(self) -> bool:
        """TCP probe of the Supabase host (no data sent)."""
        if not settings.SUPABASE_URL:
            return self.available  # injected test client
        parsed = urlparse(settings.SUPABASE_URL)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if not host:
            return False
        try:
            with socket.create_connection((host, port), timeout=settings.CONNECTIVITY_CHECK_TIMEOUT_S):
                return True
        except OSError:
            return False

    def _table(self, name: str):
        if not self._client:
            raise CloudError("Supabase client not configured")
        return self._client.table(name)

    # ------------------------------------------------------------------
    # Sensor readings
    # ------------------------------------------------------------------
    @staticmethod
    def sensor_payload(record: dict) -> dict:
        payload = {
            "local_record_id": record["local_record_id"],
            "mission_id": record.get("mission_id"),
            "device_id": record["device_id"],
            "recorded_at": record["recorded_at"],
            "latitude": record.get("latitude"),
            "longitude": record.get("longitude"),
            "heading": record.get("heading"),
            **{k: record.get(k) for k in SENSOR_FIELDS},
        }
        if settings.SUPABASE_SEND_GEOMETRY:
            lat, lon = record.get("latitude"), record.get("longitude")
            payload["position_geom"] = point_to_ewkt(lat, lon) if lat is not None and lon is not None else None
        return payload

    def upsert_sensor_reading(self, record: dict) -> None:
        """Upsert ONE record and confirm it exists in the cloud. Raises on failure."""
        payload = self.sensor_payload(record)
        table = settings.SUPABASE_SENSOR_TABLE
        resp = self._table(table).upsert(payload, on_conflict="local_record_id").execute()
        rows = getattr(resp, "data", None) or []
        if any(r.get("local_record_id") == record["local_record_id"] for r in rows if isinstance(r, dict)):
            return
        # Representation may be suppressed (RLS / prefer header): verify explicitly.
        check = (self._table(table).select("local_record_id")
                 .eq("local_record_id", record["local_record_id"]).limit(1).execute())
        if not (getattr(check, "data", None) or []):
            raise CloudError("upsert not confirmed by Supabase")

    # ------------------------------------------------------------------
    # Missions & waypoints
    # ------------------------------------------------------------------
    @staticmethod
    def mission_payload(mission: dict) -> dict:
        payload = {
            "mission_id": mission["mission_id"],
            "device_id": mission["device_id"],
            "lake_id": mission.get("lake_id"),
            "status": mission["status"],
            "waypoint_load_ack": bool(mission["waypoint_load_ack"]),
            "total_waypoints": mission["total_waypoints"],
            "current_waypoint_index": mission["current_waypoint_index"],
            "progress_percent": mission["progress_percent"],
            "started_at": mission.get("started_at"),
            "completed_at": mission.get("completed_at"),
            "created_at": mission["created_at"],
            "notes": mission.get("notes"),
        }
        if settings.SUPABASE_SEND_GEOMETRY and mission.get("polygon"):
            payload["polygon_geom"] = polygon_to_ewkt(
                [(p["latitude"], p["longitude"]) for p in mission["polygon"]]
            )
        return payload

    def upsert_mission(self, mission: dict) -> None:
        self._table(settings.SUPABASE_MISSION_TABLE).upsert(
            self.mission_payload(mission), on_conflict="mission_id"
        ).execute()

    def upsert_waypoints(self, mission_id: str, waypoints: list[dict]) -> None:
        rows = []
        for w in waypoints:
            row = {
                "mission_id": mission_id,
                "sequence_order": w["sequence_order"],
                "latitude": w["latitude"],
                "longitude": w["longitude"],
                "status": w.get("status", "PENDING"),
            }
            if settings.SUPABASE_SEND_GEOMETRY:
                row["waypoint_geom"] = point_to_ewkt(w["latitude"], w["longitude"])
            rows.append(row)
        table = self._table(settings.SUPABASE_WAYPOINT_TABLE)
        for i in range(0, len(rows), 500):  # keep request bodies small
            table.upsert(rows[i:i + 500], on_conflict="mission_id,sequence_order").execute()
