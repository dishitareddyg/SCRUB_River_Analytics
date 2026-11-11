"""
hardware/gps.py

In-memory GPS + compass state, fed entirely by the STM32 UART packet
(gps.latitude, gps.longitude, compass.heading).  Thread-safe record of
the latest values with age-based validity.  GPS and compass are tracked
independently so a heading is still available without a fix.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from config.settings import settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


@dataclass
class GPSFix:
    latitude: Optional[float]
    longitude: Optional[float]
    heading: Optional[float]   # normalised compass heading, degrees [0, 360)
    valid: bool                # position fresh and present
    age_seconds: float         # age of the position fix (inf if never)
    timestamp: Optional[float]
    heading_valid: bool = False
    heading_age_seconds: float = float("inf")


class GPSWorker:
    def __init__(self, health=None) -> None:
        self._lock = threading.Lock()
        self._latitude: Optional[float] = None
        self._longitude: Optional[float] = None
        self._heading: Optional[float] = None
        self._last_fix_time: Optional[float] = None
        self._last_heading_time: Optional[float] = None
        self._last_log_time: float = 0.0
        self._health = health

    def start(self) -> None:
        logger.info("GPS/compass driven by STM32 UART packet stream.")

    def stop(self) -> None:
        pass

    # ------------------------------------------------------------------
    def update(self, latitude: Optional[float], longitude: Optional[float],
               heading: Optional[float] = None, ts: Optional[float] = None) -> None:
        now = ts if ts is not None else time.time()
        have_fix = latitude is not None and longitude is not None
        with self._lock:
            if isinstance(heading, (int, float)):
                self._heading = float(heading) % 360.0
                self._last_heading_time = now
            if have_fix:
                self._latitude = float(latitude)
                self._longitude = float(longitude)
                self._last_fix_time = now
        if have_fix and self._health:
            self._health.set_gps_valid(True, now)
        if have_fix and now - self._last_log_time >= max(settings.GPS_UPDATE_INTERVAL_SECONDS, 10.0):
            self._last_log_time = now
            logger.info("GPS: lat=%.6f lon=%.6f heading=%s", latitude, longitude, heading)

    def get_fix(self) -> GPSFix:
        with self._lock:
            lat, lon, heading = self._latitude, self._longitude, self._heading
            fix_t, hdg_t = self._last_fix_time, self._last_heading_time
        now = time.time()
        age = now - fix_t if fix_t is not None else float("inf")
        hdg_age = now - hdg_t if hdg_t is not None else float("inf")
        valid = lat is not None and lon is not None and age <= settings.GPS_MAX_AGE_SECONDS
        heading_valid = heading is not None and hdg_age <= settings.GPS_MAX_AGE_SECONDS
        if self._health and fix_t is not None and not valid:
            self._health.set_gps_valid(False, fix_t)
        return GPSFix(
            latitude=lat, longitude=lon, heading=heading, valid=valid,
            age_seconds=age, timestamp=fix_t,
            heading_valid=heading_valid, heading_age_seconds=hdg_age,
        )
