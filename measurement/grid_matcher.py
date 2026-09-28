"""
measurement/grid_matcher.py  — verbatim from SCRUB_River_Analytics.

Grid definitions come exclusively from Supabase (never hardcoded).
GridSyncWorker refreshes the local SQLite grid_cache periodically.
GridMatcher uses Haversine nearest-centre lookup against that cache.
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

EARTH_RADIUS_M = 6_371_000.0


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


class GridMatcher:
    def __init__(self, sqlite_manager: SQLiteManager) -> None:
        self._db = sqlite_manager

    def find_matching_grid(self, latitude: float, longitude: float) -> Optional[dict]:
        grids = self._db.get_cached_grids()
        if not grids:
            return None
        best_grid = None
        best_distance = None
        for grid in grids:
            distance = haversine_distance_m(
                latitude, longitude, grid["center_lat"], grid["center_lon"]
            )
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_grid = grid
        if (
            best_grid is not None
            and best_distance is not None
            and best_distance <= settings.GRID_MATCH_RADIUS_METERS
        ):
            best_grid = dict(best_grid)
            best_grid["distance_m"] = best_distance
            return best_grid
        return None


class GridSyncWorker:
    """Periodically refreshes the local grid cache from Supabase."""

    def __init__(self, sqlite_manager: SQLiteManager, supabase_client: SupabaseClientWrapper) -> None:
        self._db = sqlite_manager
        self._supabase = supabase_client
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="GridSyncWorker", daemon=True
        )
        self._thread.start()
        logger.info(
            "GridSyncWorker started (interval=%ss)", settings.GRID_SYNC_INTERVAL_SECONDS
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run(self) -> None:
        self._sync_once()
        while not self._stop_event.is_set():
            self._stop_event.wait(settings.GRID_SYNC_INTERVAL_SECONDS)
            if not self._stop_event.is_set():
                self._sync_once()

    def _sync_once(self) -> None:
        if not self._supabase.available:
            logger.warning("Grid sync skipped — Supabase not configured/reachable")
            return
        try:
            grids = self._supabase.fetch_grids()
            self._db.replace_grid_cache(grids)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Grid sync failed, using cached grids: %s", exc)
