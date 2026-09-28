"""
config/settings.py

SINGLE CENTRAL CONFIGURATION MODULE for the Autonomous Navigation service.

Every tunable — motor power ceiling, nav packet frequency, arrival radius,
sensor thresholds, UART ports, MQTT params, Supabase credentials — lives
HERE and nowhere else. No other module should hardcode a magic number.

Values are loaded from environment variables (via a .env file if present).
See .env.example for the full list of supported variables.

KEY TUNABLES FOR ELECTRONICS TEAM
==================================
MAX_MOTOR_POWER          : absolute ceiling for left/right PWM  (default 999)
NAV_COMMAND_INTERVAL_S   : how often RPi sends a motor command to STM32 (seconds)
WAYPOINT_ARRIVAL_RADIUS_M: distance from grid centre to declare "arrived" (metres)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass


def _get_str(name: str, default: str) -> str:
    val = os.getenv(name)
    return val if val not in (None, "") else default


def _get_int(name: str, default: int) -> int:
    val = os.getenv(name)
    try:
        return int(val) if val not in (None, "") else default
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    val = os.getenv(name)
    try:
        return float(val) if val not in (None, "") else default
    except ValueError:
        return default


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class Settings:
    # -----------------------------------------------------------------------
    # Device identity
    # -----------------------------------------------------------------------
    DEVICE_ID: str = field(default_factory=lambda: _get_str("DEVICE_ID", "BOT001"))

    # -----------------------------------------------------------------------
    # MOTOR CONTROL  ← ELECTRONICS TEAM TUNABLES
    # The maximum absolute PWM value the navigation algorithm is allowed to
    # send on either motor channel.  Hardware accepts -999 to +999; tune this
    # to whatever your drive train / ESC is comfortable with during testing.
    MAX_MOTOR_POWER: int = field(default_factory=lambda: _get_int("MAX_MOTOR_POWER", 300))

    # How often (seconds) the RPi pushes a fresh motor-command packet to the
    # STM32.  Must be > 0.  The STM32 should treat silence > 2× this value as
    # a link-loss condition and halt motors.
    NAV_COMMAND_INTERVAL_S: float = field(
        default_factory=lambda: _get_float("NAV_COMMAND_INTERVAL_S", 2.0)
    )

    # Default forward cruise power (applied when heading error is zero).
    # Navigation algorithm will scale this proportionally.  Must be ≤ MAX_MOTOR_POWER.
    DEFAULT_CRUISE_POWER: int = field(
        default_factory=lambda: _get_int("DEFAULT_CRUISE_POWER", 150)
    )

    # Proportional steering gain.  heading_error_deg * STEERING_K gives the
    # differential PWM offset applied to left vs. right motor.
    STEERING_K: float = field(default_factory=lambda: _get_float("STEERING_K", 1.5))

    # -----------------------------------------------------------------------
    # NAVIGATION — arrival & safety
    # -----------------------------------------------------------------------
    # A GPS position is declared "arrived at grid centre" when the bot is
    # within this radius (metres).  Matches the sensor-collection radius used
    # by the SCRUB pipeline — same grid, same point.
    WAYPOINT_ARRIVAL_RADIUS_M: float = field(
        default_factory=lambda: _get_float("WAYPOINT_ARRIVAL_RADIUS_M", 5.0)
    )

    # Optional geofence: max distance (metres) the bot may stray from the
    # mission start point.  Set to 0 to disable.
    GEOFENCE_RADIUS_M: float = field(
        default_factory=lambda: _get_float("GEOFENCE_RADIUS_M", 500.0)
    )

    # GPS watchdog: if no valid GPS fix arrives for this many seconds while
    # NAVIGATING, motors are stopped and state goes to GPS_LOST.
    GPS_LOSS_TIMEOUT_S: float = field(
        default_factory=lambda: _get_float("GPS_LOSS_TIMEOUT_S", 10.0)
    )

    # Maximum total mission runtime (seconds).  Prevents runaway missions.
    MAX_MISSION_RUNTIME_S: float = field(
        default_factory=lambda: _get_float("MAX_MISSION_RUNTIME_S", 7200.0)
    )

    # -----------------------------------------------------------------------
    # STM32 UART — sole hardware link
    # All sensors, GPS, compass and motors are wired to the STM32 which
    # relays a combined JSON packet to the RPi at ~0.5 Hz AND accepts
    # motor-command packets from the RPi.
    # -----------------------------------------------------------------------
    STM32_SERIAL_PORT: str = field(
        default_factory=lambda: _get_str("STM32_SERIAL_PORT", "/dev/ttyAMA1")
    )
    STM32_BAUDRATE: int = field(default_factory=lambda: _get_int("STM32_BAUDRATE", 115200))
    STM32_SERIAL_TIMEOUT: float = field(
        default_factory=lambda: _get_float("STM32_SERIAL_TIMEOUT", 2.0)
    )

    # -----------------------------------------------------------------------
    # Timing — sensor & GPS
    # -----------------------------------------------------------------------
    # STM32 sends one combined packet (motors+gps+compass+sensors) ~every 2 s.
    SENSOR_PACKET_INTERVAL_SECONDS: float = field(
        default_factory=lambda: _get_float("SENSOR_PACKET_INTERVAL_SECONDS", 2.0)
    )
    # While motors IDLE and within grid radius, collect one sample every N s.
    SENSOR_SAMPLE_INTERVAL_SECONDS: float = field(
        default_factory=lambda: _get_float("SENSOR_SAMPLE_INTERVAL_SECONDS", 6.0)
    )
    GPS_UPDATE_INTERVAL_SECONDS: float = field(
        default_factory=lambda: _get_float("GPS_UPDATE_INTERVAL_SECONDS", 2.0)
    )
    # GPS fix older than this is considered stale.
    GPS_MAX_AGE_SECONDS: float = field(
        default_factory=lambda: _get_float("GPS_MAX_AGE_SECONDS", 6.0)
    )
    # Motor state reported by STM32 is trusted for this long.
    MOTOR_STATE_MAX_AGE_SECONDS: float = field(
        default_factory=lambda: _get_float("MOTOR_STATE_MAX_AGE_SECONDS", 6.0)
    )

    # -----------------------------------------------------------------------
    # Mission & grid
    # -----------------------------------------------------------------------
    MAX_READINGS_PER_GRID: int = field(
        default_factory=lambda: _get_int("MAX_READINGS_PER_GRID", 10)
    )
    GRID_MATCH_RADIUS_METERS: float = field(
        default_factory=lambda: _get_float("GRID_MATCH_RADIUS_METERS", 5.0)
    )
    GRID_SYNC_INTERVAL_SECONDS: float = field(
        default_factory=lambda: _get_float("GRID_SYNC_INTERVAL_SECONDS", 60.0)
    )
    # How often the mission worker polls Supabase for a new PENDING mission.
    MISSION_POLL_INTERVAL_SECONDS: float = field(
        default_factory=lambda: _get_float("MISSION_POLL_INTERVAL_SECONDS", 10.0)
    )

    # -----------------------------------------------------------------------
    # MQTT
    # -----------------------------------------------------------------------
    MQTT_BROKER_HOST: str = field(
        default_factory=lambda: _get_str("MQTT_BROKER_HOST", "localhost")
    )
    MQTT_BROKER_PORT: int = field(
        default_factory=lambda: _get_int("MQTT_BROKER_PORT", 1883)
    )
    MQTT_USERNAME: str = field(default_factory=lambda: _get_str("MQTT_USERNAME", ""))
    MQTT_PASSWORD: str = field(default_factory=lambda: _get_str("MQTT_PASSWORD", ""))
    MQTT_CLIENT_ID: str = field(
        default_factory=lambda: _get_str("MQTT_CLIENT_ID", "lake-bot-autonomous")
    )
    MQTT_KEEPALIVE: int = field(default_factory=lambda: _get_int("MQTT_KEEPALIVE", 30))
    MQTT_QOS: int = field(default_factory=lambda: _get_int("MQTT_QOS", 1))
    MQTT_RETAIN: bool = field(default_factory=lambda: _get_bool("MQTT_RETAIN", False))
    MQTT_RECONNECT_DELAY: int = field(
        default_factory=lambda: _get_int("MQTT_RECONNECT_DELAY", 5)
    )
    MQTT_BASE_TOPIC: str = field(
        default_factory=lambda: _get_str("MQTT_BASE_TOPIC", "lakebot")
    )

    # -----------------------------------------------------------------------
    # Supabase
    # -----------------------------------------------------------------------
    SUPABASE_URL: str = field(default_factory=lambda: _get_str("SUPABASE_URL", ""))
    SUPABASE_KEY: str = field(default_factory=lambda: _get_str("SUPABASE_KEY", ""))

    # -----------------------------------------------------------------------
    # Sensor validation ranges
    # -----------------------------------------------------------------------
    PH_MIN: float = field(default_factory=lambda: _get_float("PH_MIN", 0.0))
    PH_MAX: float = field(default_factory=lambda: _get_float("PH_MAX", 14.0))
    TDS_MIN: float = field(default_factory=lambda: _get_float("TDS_MIN", 0.0))
    TDS_MAX: float = field(default_factory=lambda: _get_float("TDS_MAX", 5000.0))
    TURBIDITY_MIN: float = field(default_factory=lambda: _get_float("TURBIDITY_MIN", 0.0))
    TURBIDITY_MAX: float = field(default_factory=lambda: _get_float("TURBIDITY_MAX", 3000.0))
    TEMPERATURE_MIN: float = field(default_factory=lambda: _get_float("TEMPERATURE_MIN", -10.0))
    TEMPERATURE_MAX: float = field(default_factory=lambda: _get_float("TEMPERATURE_MAX", 60.0))
    HUMIDITY_MIN: float = field(default_factory=lambda: _get_float("HUMIDITY_MIN", 0.0))
    HUMIDITY_MAX: float = field(default_factory=lambda: _get_float("HUMIDITY_MAX", 100.0))

    # -----------------------------------------------------------------------
    # SQLite local buffer
    # -----------------------------------------------------------------------
    SQLITE_PATH: str = field(
        default_factory=lambda: _get_str(
            "SQLITE_PATH", str(_PROJECT_ROOT / "data" / "autonomous_nav.db")
        )
    )

    # -----------------------------------------------------------------------
    # Cloud upload
    # -----------------------------------------------------------------------
    UPLOAD_POLL_INTERVAL_SECONDS: float = field(
        default_factory=lambda: _get_float("UPLOAD_POLL_INTERVAL_SECONDS", 5.0)
    )
    UPLOAD_BATCH_SIZE: int = field(default_factory=lambda: _get_int("UPLOAD_BATCH_SIZE", 20))
    # 0 = retry forever (never discard an accepted reading)
    UPLOAD_MAX_RETRIES: int = field(default_factory=lambda: _get_int("UPLOAD_MAX_RETRIES", 0))

    # -----------------------------------------------------------------------
    # Health / monitoring
    # -----------------------------------------------------------------------
    HEALTH_PUBLISH_INTERVAL_SECONDS: float = field(
        default_factory=lambda: _get_float("HEALTH_PUBLISH_INTERVAL_SECONDS", 10.0)
    )

    # -----------------------------------------------------------------------
    # Logging
    # -----------------------------------------------------------------------
    LOG_LEVEL: str = field(default_factory=lambda: _get_str("LOG_LEVEL", "INFO"))


# Singleton settings instance used throughout the application.
settings = Settings()
