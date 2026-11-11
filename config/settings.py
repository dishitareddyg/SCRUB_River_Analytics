"""
config/settings.py

SINGLE CENTRAL CONFIGURATION MODULE for the Autonomous Lake Cleaning Bot.

Every tunable lives HERE and nowhere else: UART, motor limits, steering,
navigation tolerances, sensor storage cadence, cloud upload cadence,
MQTT, Supabase, API security and logging.

Values are loaded from environment variables (via a .env file if present).
See .env.example for the full list of supported variables.

"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(os.getenv("LAKEBOT_ENV_FILE", str(_PROJECT_ROOT / ".env")))
except ImportError:
    pass

# Hardware PWM range accepted by the STM32 (SOFTWARE ARCHITECTURE.docx).
HARDWARE_PWM_LIMIT = 999


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


def _get_list(name: str, default: str) -> tuple[str, ...]:
    raw = _get_str(name, default)
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _data_path(name: str, filename: str) -> str:
    return _get_str(name, str(_PROJECT_ROOT / "data" / filename))


@dataclass(frozen=True)
class Settings:
    # ------------------------------------------------------------------
    # Device identity & local persistence
    # ------------------------------------------------------------------
    DEVICE_ID: str = field(default_factory=lambda: _get_str("DEVICE_ID", "BOT001"))
    SQLITE_PATH: str = field(default_factory=lambda: _data_path("SQLITE_PATH", "autonomous_nav.db"))
    WAYPOINT_JSON_PATH: str = field(
        default_factory=lambda: _data_path("WAYPOINT_JSON_PATH", "waypoints.json")
    )

    # ------------------------------------------------------------------
    # STM32 UART (sole hardware link)
    # ------------------------------------------------------------------
    STM32_SERIAL_PORT: str = field(default_factory=lambda: _get_str("STM32_SERIAL_PORT", "/dev/ttyAMA1"))
    STM32_BAUDRATE: int = field(default_factory=lambda: _get_int("STM32_BAUDRATE", 115200))
    # pyserial read timeout (seconds); keeps the reader responsive to shutdown.
    STM32_SERIAL_TIMEOUT: float = field(default_factory=lambda: _get_float("STM32_SERIAL_TIMEOUT", 1.0))
    STM32_WRITE_TIMEOUT: float = field(default_factory=lambda: _get_float("STM32_WRITE_TIMEOUT", 1.0))
    STM32_RECONNECT_DELAY_S: float = field(default_factory=lambda: _get_float("STM32_RECONNECT_DELAY_S", 3.0))
    # Expected STM32 -> RPi packet interval (documented: 1 packet / 2 s).
    STM32_PACKET_INTERVAL_S: float = field(default_factory=lambda: _get_float("STM32_PACKET_INTERVAL_S", 2.0))
    # No packet for this long => link considered down (default 3 missed packets).
    STM32_LINK_TIMEOUT_S: float = field(default_factory=lambda: _get_float("STM32_LINK_TIMEOUT_S", 6.0))

    # ------------------------------------------------------------------
    # Motor command (RPi -> STM32), documented: 1 packet / 2 s
    # {"left":"+100","right":"+100","mode":"auto"}
    # ------------------------------------------------------------------
    MOTOR_COMMAND_INTERVAL_S: float = field(default_factory=lambda: _get_float("MOTOR_COMMAND_INTERVAL_S", 2.0))
    MOTOR_COMMAND_MODE: str = field(default_factory=lambda: _get_str("MOTOR_COMMAND_MODE", "auto"))
    # Software ceiling for |PWM|; never exceeds the hardware limit of 999.
    MAX_MOTOR_POWER: int = field(
        default_factory=lambda: min(abs(_get_int("MAX_MOTOR_POWER", 300)), HARDWARE_PWM_LIMIT)
    )
    DEFAULT_CRUISE_POWER: int = field(default_factory=lambda: _get_int("DEFAULT_CRUISE_POWER", 150))
    # Motor state reported by the STM32 is trusted for this long.
    MOTOR_STATE_MAX_AGE_SECONDS: float = field(
        default_factory=lambda: _get_float("MOTOR_STATE_MAX_AGE_SECONDS", 6.0)
    )

    # ------------------------------------------------------------------
    # Steering
    # ------------------------------------------------------------------
    # pwm_left = cruise + K * error_deg ; pwm_right = cruise - K * error_deg
    STEERING_K: float = field(default_factory=lambda: _get_float("STEERING_K", 1.5))
    # Below this distance cruise power is scaled down linearly (0 = disabled).
    APPROACH_SLOWDOWN_RADIUS_M: float = field(
        default_factory=lambda: _get_float("APPROACH_SLOWDOWN_RADIUS_M", 0.0)
    )
    MIN_CRUISE_POWER: int = field(default_factory=lambda: _get_int("MIN_CRUISE_POWER", 80))

    # ------------------------------------------------------------------
    # Compass
    # ------------------------------------------------------------------
    # true_heading = (raw_heading + COMPASS_OFFSET_DEG + COMPASS_DECLINATION_DEG) % 360
    COMPASS_OFFSET_DEG: float = field(default_factory=lambda: _get_float("COMPASS_OFFSET_DEG", 0.0))
    COMPASS_DECLINATION_DEG: float = field(default_factory=lambda: _get_float("COMPASS_DECLINATION_DEG", 0.0))

    # ------------------------------------------------------------------
    # GPS & navigation
    # ------------------------------------------------------------------
    GPS_UPDATE_INTERVAL_SECONDS: float = field(default_factory=lambda: _get_float("GPS_UPDATE_INTERVAL_SECONDS", 2.0))
    # A fix older than this is stale (not used for steering).
    GPS_MAX_AGE_SECONDS: float = field(default_factory=lambda: _get_float("GPS_MAX_AGE_SECONDS", 6.0))
    # Treat (0, 0) as "no fix" (common GPS-module default).
    GPS_REJECT_NULL_ISLAND: bool = field(default_factory=lambda: _get_bool("GPS_REJECT_NULL_ISLAND", True))
    # How often the navigator recomputes the desired motor command.
    NAV_UPDATE_INTERVAL_S: float = field(default_factory=lambda: _get_float("NAV_UPDATE_INTERVAL_S", 2.0))
    WAYPOINT_ARRIVAL_RADIUS_M: float = field(default_factory=lambda: _get_float("WAYPOINT_ARRIVAL_RADIUS_M", 3.0))
    # GPS stale for this long while ACTIVE => mission auto-PAUSED (motors 0).
    GPS_LOSS_TIMEOUT_S: float = field(default_factory=lambda: _get_float("GPS_LOSS_TIMEOUT_S", 10.0))
    # Max seconds to reach a single waypoint before auto-PAUSE (0 = disabled).
    WAYPOINT_TIMEOUT_S: float = field(default_factory=lambda: _get_float("WAYPOINT_TIMEOUT_S", 600.0))
    # Max total active mission runtime before FAILED (0 = disabled).
    MAX_MISSION_RUNTIME_S: float = field(default_factory=lambda: _get_float("MAX_MISSION_RUNTIME_S", 7200.0))
    # Max distance from GCS before auto-PAUSE (0 = disabled).
    GEOFENCE_RADIUS_M: float = field(default_factory=lambda: _get_float("GEOFENCE_RADIUS_M", 1000.0))

    # ------------------------------------------------------------------
    # Mission validation
    # ------------------------------------------------------------------
    MAX_MISSION_WAYPOINTS: int = field(default_factory=lambda: _get_int("MAX_MISSION_WAYPOINTS", 5000))
    MAX_POLYGON_VERTICES: int = field(default_factory=lambda: _get_int("MAX_POLYGON_VERTICES", 500))
    # GCS waypoints must be within this distance of ground_control.
    GCS_MATCH_TOLERANCE_M: float = field(default_factory=lambda: _get_float("GCS_MATCH_TOLERANCE_M", 1.0))
    # Coverage waypoints may lie at most this far outside the polygon edge.
    POLYGON_TOLERANCE_M: float = field(default_factory=lambda: _get_float("POLYGON_TOLERANCE_M", 2.0))
    # Start / resume preconditions (safety): live STM32 link and a fresh GPS fix.
    START_REQUIRES_STM32_LINK: bool = field(default_factory=lambda: _get_bool("START_REQUIRES_STM32_LINK", True))
    START_REQUIRES_GPS_FIX: bool = field(default_factory=lambda: _get_bool("START_REQUIRES_GPS_FIX", True))

    # ------------------------------------------------------------------
    # Sensor storage (latest state persisted once per interval)
    # ------------------------------------------------------------------
    SENSOR_STORE_INTERVAL_S: float = field(default_factory=lambda: _get_float("SENSOR_STORE_INTERVAL_S", 10.0))
    # Skip a snapshot if the newest STM32 packet is older than this.
    SENSOR_MAX_AGE_S: float = field(default_factory=lambda: _get_float("SENSOR_MAX_AGE_S", 6.0))

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

    # ------------------------------------------------------------------
    # Cloud (Supabase) — sensor upload is rate limited to ONE record / interval
    # ------------------------------------------------------------------
    SUPABASE_URL: str = field(default_factory=lambda: _get_str("SUPABASE_URL", ""))
    SUPABASE_KEY: str = field(default_factory=lambda: _get_str("SUPABASE_KEY", ""))
    SUPABASE_TIMEOUT_S: float = field(default_factory=lambda: _get_float("SUPABASE_TIMEOUT_S", 8.0))
    SUPABASE_SENSOR_TABLE: str = field(default_factory=lambda: _get_str("SUPABASE_SENSOR_TABLE", "sensor_readings"))
    SUPABASE_MISSION_TABLE: str = field(default_factory=lambda: _get_str("SUPABASE_MISSION_TABLE", "missions"))
    SUPABASE_WAYPOINT_TABLE: str = field(
        default_factory=lambda: _get_str("SUPABASE_WAYPOINT_TABLE", "mission_waypoints")
    )
    # Send PostGIS geometry columns as EWKT (SRID=4326). Disable if the
    # deployed schema fills geometry with a trigger instead.
    SUPABASE_SEND_GEOMETRY: bool = field(default_factory=lambda: _get_bool("SUPABASE_SEND_GEOMETRY", True))
    # Minimum spacing between sensor upload attempts (never lower than this).
    UPLOAD_INTERVAL_S: float = field(default_factory=lambda: _get_float("UPLOAD_INTERVAL_S", 10.0))
    # 0 = retry forever (records are never deleted either way).
    UPLOAD_MAX_RETRIES: int = field(default_factory=lambda: _get_int("UPLOAD_MAX_RETRIES", 0))
    UPLOAD_RETRY_BASE_S: float = field(default_factory=lambda: _get_float("UPLOAD_RETRY_BASE_S", 10.0))
    UPLOAD_RETRY_MAX_S: float = field(default_factory=lambda: _get_float("UPLOAD_RETRY_MAX_S", 300.0))
    MISSION_SYNC_INTERVAL_S: float = field(default_factory=lambda: _get_float("MISSION_SYNC_INTERVAL_S", 5.0))
    CONNECTIVITY_CHECK_TIMEOUT_S: float = field(
        default_factory=lambda: _get_float("CONNECTIVITY_CHECK_TIMEOUT_S", 3.0)
    )

    # ------------------------------------------------------------------
    # MQTT live telemetry
    # ------------------------------------------------------------------
    MQTT_ENABLED: bool = field(default_factory=lambda: _get_bool("MQTT_ENABLED", True))
    MQTT_BROKER_HOST: str = field(default_factory=lambda: _get_str("MQTT_BROKER_HOST", "localhost"))
    MQTT_BROKER_PORT: int = field(default_factory=lambda: _get_int("MQTT_BROKER_PORT", 1883))
    MQTT_USERNAME: str = field(default_factory=lambda: _get_str("MQTT_USERNAME", ""))
    MQTT_PASSWORD: str = field(default_factory=lambda: _get_str("MQTT_PASSWORD", ""))
    MQTT_CLIENT_ID: str = field(default_factory=lambda: _get_str("MQTT_CLIENT_ID", "lake-bot-autonomous"))
    MQTT_KEEPALIVE: int = field(default_factory=lambda: _get_int("MQTT_KEEPALIVE", 30))
    MQTT_QOS: int = field(default_factory=lambda: _get_int("MQTT_QOS", 0))
    MQTT_RETAIN: bool = field(default_factory=lambda: _get_bool("MQTT_RETAIN", False))
    MQTT_RECONNECT_DELAY: int = field(default_factory=lambda: _get_int("MQTT_RECONNECT_DELAY", 5))
    MQTT_BASE_TOPIC: str = field(default_factory=lambda: _get_str("MQTT_BASE_TOPIC", "lakebot"))
    # Topics are "<base>/<device_id>/<suffix>"
    MQTT_TOPIC_TELEMETRY: str = field(default_factory=lambda: _get_str("MQTT_TOPIC_TELEMETRY", "telemetry"))
    MQTT_TOPIC_HEALTH: str = field(default_factory=lambda: _get_str("MQTT_TOPIC_HEALTH", "health"))
    MQTT_TOPIC_MISSION: str = field(default_factory=lambda: _get_str("MQTT_TOPIC_MISSION", "mission"))
    TELEMETRY_INTERVAL_S: float = field(default_factory=lambda: _get_float("TELEMETRY_INTERVAL_S", 2.0))
    HEALTH_PUBLISH_INTERVAL_SECONDS: float = field(
        default_factory=lambda: _get_float("HEALTH_PUBLISH_INTERVAL_SECONDS", 10.0)
    )

    # ------------------------------------------------------------------
    # HTTP API / WebSocket
    # ------------------------------------------------------------------
    API_ENABLED: bool = field(default_factory=lambda: _get_bool("API_ENABLED", True))
    API_HOST: str = field(default_factory=lambda: _get_str("API_HOST", "0.0.0.0"))
    API_PORT: int = field(default_factory=lambda: _get_int("API_PORT", 8000))
    # Shared secret. Required in production; empty disables auth (dev only).
    API_AUTH_TOKEN: str = field(default_factory=lambda: _get_str("API_AUTH_TOKEN", ""))
    CORS_ALLOWED_ORIGINS: tuple = field(
        default_factory=lambda: _get_list("CORS_ALLOWED_ORIGINS", "http://localhost:5173")
    )
    WS_MAX_CLIENTS: int = field(default_factory=lambda: _get_int("WS_MAX_CLIENTS", 20))

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    LOG_LEVEL: str = field(default_factory=lambda: _get_str("LOG_LEVEL", "INFO"))
    LOG_FORMAT: str = field(
        default_factory=lambda: _get_str("LOG_FORMAT", "%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )


# Singleton settings instance used throughout the application.
settings = Settings()
