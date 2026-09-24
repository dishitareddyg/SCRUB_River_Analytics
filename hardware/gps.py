"""
hardware/gps.py

GPS + compass position state, fed entirely by the STM32 combined UART
packet (see hardware/stm32.py). There is NO dedicated GPS serial port on
the RPi 5 anymore -- the NEO-M8N GPS/compass module is wired to the
STM32, which relays the latest fix/heading to the RPi inside its 0.5 Hz
JSON packet. This module simply keeps a thread-safe, in-memory record of
the LATEST value reported for each and applies the same age-based
validity rule the previous dedicated-serial implementation used.

Design goals (unchanged from the previous architecture, spec section 9):
  - Never blocks any other subsystem -- it only touches its own
    in-memory state object, guarded by a lock.
  - Maintains latest_latitude / latest_longitude / latest_heading /
    gps_fix_valid / gps_timestamp.
  - If the STM32 link goes stale (no packet for GPS_MAX_AGE_SECONDS),
    consumers must see gps_fix_valid=False. This is achieved by an
    AGE-BASED validity check on read (same mechanism as before) -- no
    separate watchdog needed.

Obsolete (removed) with this architecture change:
  - Direct serial connection to the NEO-M8N (pyserial + pynmea2 NMEA
    sentence parsing) -- the RPi no longer has GPS wired to it directly.
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
    valid: bool
    age_seconds: float
    timestamp: Optional[float]
    # Latest compass heading (degrees), reported alongside the GPS fix
    # in the same STM32 packet. Optional/defaulted so existing callers
    # that construct GPSFix positionally/by keyword without it keep working.
    heading: Optional[float] = None


class GPSWorker:
    """Thread-safe holder for the latest GPS fix + compass heading,
    updated by the STM32 UART pipeline (measurement_manager) rather than
    by its own serial thread."""

    def __init__(self, health=None):
        self._lock = threading.Lock()
        self._latitude: Optional[float] = None
        self._longitude: Optional[float] = None
        self._heading: Optional[float] = None
        self._last_fix_time: Optional[float] = None
        self._last_log_time: float = 0.0
        self._health = health

    # ------------------------------------------------------------------
    # Lifecycle -- kept as no-ops so main.py's start/stop wiring does not
    # need to change: there is no dedicated serial thread to manage now.
    # ------------------------------------------------------------------
    def start(self) -> None:
        logger.info("GPS/compass now driven by the STM32 UART packet stream (no dedicated GPS serial port)")

    def stop(self) -> None:
        pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def update(self, latitude: Optional[float], longitude: Optional[float],
               heading: Optional[float] = None, ts: Optional[float] = None) -> None:
        """Record a fresh GPS/compass reading extracted from an STM32
        packet. latitude/longitude are required for the fix to be
        considered updated; heading is best-effort and may be None if
        the compass reading in that packet was missing/invalid."""
        if latitude is None or longitude is None:
            return
        now = ts if ts is not None else time.time()
        with self._lock:
            self._latitude = float(latitude)
            self._longitude = float(longitude)
            self._heading = float(heading) if isinstance(heading, (int, float)) else self._heading
            self._last_fix_time = now

        if self._health:
            self._health.set_gps_valid(True, now)

        if now - self._last_log_time >= settings.GPS_UPDATE_INTERVAL_SECONDS:
            self._last_log_time = now
            logger.info("GPS position updated: lat=%.6f lon=%.6f heading=%s", latitude, longitude, heading)

    def get_fix(self) -> GPSFix:
        """Return the latest fix with a freshness/validity check applied."""
        with self._lock:
            lat, lon, heading, last_fix_time = (
                self._latitude, self._longitude, self._heading, self._last_fix_time
            )

        if last_fix_time is None:
            return GPSFix(latitude=None, longitude=None, valid=False,
                           age_seconds=float("inf"), timestamp=None, heading=None)

        age = time.time() - last_fix_time
        valid = age <= settings.GPS_MAX_AGE_SECONDS
        return GPSFix(latitude=lat, longitude=lon, valid=valid, age_seconds=age,
                       timestamp=last_fix_time, heading=heading)
