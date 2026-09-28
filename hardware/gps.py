"""
hardware/gps.py

In-memory GPS + compass state, fed entirely by the STM32 combined UART
packet (see hardware/stm32.py).  The NEO-M8N GPS and compass are wired
to the STM32 which relays the latest fix + heading in its 0.5 Hz JSON.
This module keeps a thread-safe record of the latest values and applies
age-based validity — exactly the same mechanism as SCRUB_River_Analytics.
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
    heading: Optional[float]   # compass heading, degrees [0, 360)
    valid: bool
    age_seconds: float
    timestamp: Optional[float]


class GPSWorker:
    """Thread-safe holder for the latest GPS fix + compass heading.
    Updated by MeasurementManager / Navigator on each STM32 packet."""

    def __init__(self, health=None) -> None:
        self._lock = threading.Lock()
        self._latitude: Optional[float] = None
        self._longitude: Optional[float] = None
        self._heading: Optional[float] = None
        self._last_fix_time: Optional[float] = None
        self._last_log_time: float = 0.0
        self._health = health

    # Lifecycle: kept as no-ops (no dedicated serial thread).
    def start(self) -> None:
        logger.info("GPS/compass driven by STM32 UART packet stream.")

    def stop(self) -> None:
        pass

    # ------------------------------------------------------------------
    def update(
        self,
        latitude: Optional[float],
        longitude: Optional[float],
        heading: Optional[float] = None,
        ts: Optional[float] = None,
    ) -> None:
        """Record fresh GPS/compass data extracted from an STM32 packet."""
        if latitude is None or longitude is None:
            return
        now = ts if ts is not None else time.time()
        with self._lock:
            self._latitude = float(latitude)
            self._longitude = float(longitude)
            if isinstance(heading, (int, float)):
                self._heading = float(heading)
            self._last_fix_time = now

        if self._health:
            self._health.set_gps_valid(True, now)

        if now - self._last_log_time >= settings.GPS_UPDATE_INTERVAL_SECONDS:
            self._last_log_time = now
            logger.info(
                "GPS updated: lat=%.6f lon=%.6f heading=%s",
                latitude, longitude, heading,
            )

    def get_fix(self) -> GPSFix:
        """Return the latest fix with freshness check applied."""
        with self._lock:
            lat = self._latitude
            lon = self._longitude
            heading = self._heading
            last_fix_time = self._last_fix_time

        if last_fix_time is None:
            return GPSFix(
                latitude=None, longitude=None, heading=None,
                valid=False, age_seconds=float("inf"), timestamp=None,
            )

        age = time.time() - last_fix_time
        valid = (lat is not None and lon is not None
                 and age <= settings.GPS_MAX_AGE_SECONDS)
        return GPSFix(
            latitude=lat, longitude=lon, heading=heading,
            valid=valid, age_seconds=age, timestamp=last_fix_time,
        )
