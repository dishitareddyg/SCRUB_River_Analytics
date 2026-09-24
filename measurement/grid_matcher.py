"""
measurement/grid_matcher.py

Grid definitions come EXCLUSIVELY from Supabase (spec section 7) -- never
hardcoded here. A background sync (GridSyncWorker) periodically refreshes
a local cache (grid_cache table) so matching keeps working even during a
temporary cloud outage.

Matching logic (spec section 8):
  - Uses a lightweight Haversine distance calculation (no heavy GIS).
  - A GPS position matches a grid only if within GRID_MATCH_RADIUS_METERS
    of that grid's cached center.
  - If multiple grids are within range, the nearest one wins (deterministic).
"""

from __future__ import annotations

import math
import threading
import time
from typing import Optional

from cloud.supabase_client import SupabaseClientWrapper
from config.settings import settings
from monitoring.logger import get_logger
from storage.sqlite_manager import SQLiteManager

logger = get_logger(__name__)

EARTH_RADIUS_M = 6371000.0


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


class GridMatcher:
    def __init__(self, sqlite_manager: SQLiteManager):
        self._db = sqlite_manager

    def find_matching_grid(self, latitude: float, longitude: float) -> Optional[dict]:
        grids = self._db.get_cached_grids()
        if not grids:
            return None

        best_grid = None
        best_distance = None
        for grid in grids:
            distance = haversine_distance_m(latitude, longitude, grid["center_lat"], grid["center_lon"])
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_grid = grid

        if best_grid is not None and best_distance is not None and best_distance <= settings.GRID_MATCH_RADIUS_METERS:
            best_grid = dict(best_grid)
            best_grid["distance_m"] = best_distance
            return best_grid
        return None


class GridSyncWorker:
    """Periodically refreshes the local grid cache from Supabase."""

    def __init__(self, sqlite_manager: SQLiteManager, supabase_client: SupabaseClientWrapper):
        self._db = sqlite_manager
        self._supabase = supabase_client
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="GridSyncWorker", daemon=True)
        self._thread.start()
        logger.info("Grid sync worker started (interval=%ss)", settings.GRID_SYNC_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        # Sync once immediately at startup so matching works right away.
        self._sync_once()
        while not self._stop_event.is_set():
            self._stop_event.wait(settings.GRID_SYNC_INTERVAL_SECONDS)
            if not self._stop_event.is_set():
                self._sync_once()

    def _sync_once(self) -> None:
        if not self._supabase.available:
            logger.warning("Grid sync skipped -- Supabase not configured/reachable")
            return
        try:
            grids = self._supabase.fetch_grids()
            self._db.replace_grid_cache(grids)
        except Exception as exc:  # noqa: BLE001 - keep using stale cache on failure
            logger.warning("Grid sync failed, continuing with cached grids: %s", exc)
