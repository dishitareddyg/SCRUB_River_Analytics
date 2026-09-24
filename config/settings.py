"""
config/settings.py

SINGLE CENTRAL CONFIGURATION MODULE.

Every tunable value in the backend (timing, thresholds, ports, credentials,
MQTT parameters, validation ranges, etc.) is defined/loaded HERE and nowhere
else. No other module should hardcode a magic number that belongs here.

Values are loaded from environment variables (via a .env file if present).
See .env.example for the full list of supported variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (if present). Real deployments should place
# a .env file next to main.py; python-dotenv silently no-ops if missing.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


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
    # --- Device identity ---
    DEVICE_ID: str = field(default_factory=lambda: _get_str("DEVICE_ID", "BOT001"))

    # --- Core business-rule configuration (see prompt RULE 6/7) ---
    MAX_READINGS_PER_GRID: int = field(default_factory=lambda: _get_int("MAX_READINGS_PER_GRID", 10))
    GRID_MATCH_RADIUS_METERS: float = field(default_factory=lambda: _get_float("GRID_MATCH_RADIUS_METERS", 5.0))

    # --- Timing ---
    # NOTE (new STM32 <-> RPi5 architecture): the STM32 now sends ONE
    # combined JSON packet (motors + gps + compass + sensors) at 0.5 Hz,
    # i.e. every ~2 seconds. GPS/compass telemetry is refreshed on every
    # such packet. Sensor SAMPLING (persisted readings) is intentionally
    # slower than the packet rate -- see SENSOR_SAMPLE_INTERVAL_SECONDS.
    GPS_UPDATE_INTERVAL_SECONDS: float = field(default_factory=lambda: _get_float("GPS_UPDATE_INTERVAL_SECONDS", 2))
    SENSOR_PACKET_INTERVAL_SECONDS: float = field(default_factory=lambda: _get_float("SENSOR_PACKET_INTERVAL_SECONDS", 2))
    # While motors are IDLE (and grid/GPS validity holds), collect
    # exactly one sensor sample every SENSOR_SAMPLE_INTERVAL_SECONDS,
    # rather than on every 0.5 Hz STM32 packet.
    SENSOR_SAMPLE_INTERVAL_SECONDS: float = field(default_factory=lambda: _get_float("SENSOR_SAMPLE_INTERVAL_SECONDS", 6))
    GPS_MAX_AGE_SECONDS: float = field(default_factory=lambda: _get_float("GPS_MAX_AGE_SECONDS", 6))
    MOTOR_STATE_MAX_AGE_SECONDS: float = field(default_factory=lambda: _get_float("MOTOR_STATE_MAX_AGE_SECONDS", 3))
    GRID_SYNC_INTERVAL_SECONDS: float = field(default_factory=lambda: _get_float("GRID_SYNC_INTERVAL_SECONDS", 60))
    UPLOAD_POLL_INTERVAL_SECONDS: float = field(default_factory=lambda: _get_float("UPLOAD_POLL_INTERVAL_SECONDS", 5))
    HEALTH_PUBLISH_INTERVAL_SECONDS: float = field(default_factory=lambda: _get_float("HEALTH_PUBLISH_INTERVAL_SECONDS", 10))

    # --- STM32 UART ---
    # SOLE hardware input to the RPi 5. All sensors, the NEO-M8N
    # GPS/compass, motors and the RC controller are wired to the STM32,
    # which relays one combined JSON packet per cycle over this link.
    # There is no longer a separate GPS serial port or Arduino/USB motor
    # link on the RPi (see hardware/gps.py and hardware/motor_controller.py).
    STM32_SERIAL_PORT: str = field(default_factory=lambda: _get_str("STM32_SERIAL_PORT", "/dev/ttyAMA1"))
    STM32_BAUDRATE: int = field(default_factory=lambda: _get_int("STM32_BAUDRATE", 115200))
    STM32_SERIAL_TIMEOUT: float = field(default_factory=lambda: _get_float("STM32_SERIAL_TIMEOUT", 2.0))

    # --- MQTT (all MQTT constants centralized here, per spec section 4) ---
    MQTT_BROKER_HOST: str = field(default_factory=lambda: _get_str("MQTT_BROKER_HOST", "localhost"))
    MQTT_BROKER_PORT: int = field(default_factory=lambda: _get_int("MQTT_BROKER_PORT", 1883))
    MQTT_USERNAME: str = field(default_factory=lambda: _get_str("MQTT_USERNAME", ""))
    MQTT_PASSWORD: str = field(default_factory=lambda: _get_str("MQTT_PASSWORD", ""))
    MQTT_CLIENT_ID: str = field(default_factory=lambda: _get_str("MQTT_CLIENT_ID", "lake-bot-backend"))
    MQTT_KEEPALIVE: int = field(default_factory=lambda: _get_int("MQTT_KEEPALIVE", 30))
    MQTT_QOS: int = field(default_factory=lambda: _get_int("MQTT_QOS", 1))
    MQTT_RETAIN: bool = field(default_factory=lambda: _get_bool("MQTT_RETAIN", False))
    MQTT_RECONNECT_DELAY: int = field(default_factory=lambda: _get_int("MQTT_RECONNECT_DELAY", 5))
    MQTT_BASE_TOPIC: str = field(default_factory=lambda: _get_str("MQTT_BASE_TOPIC", "lakebot"))

    # --- Supabase ---
    SUPABASE_URL: str = field(default_factory=lambda: _get_str("SUPABASE_URL", ""))
    SUPABASE_KEY: str = field(default_factory=lambda: _get_str("SUPABASE_KEY", ""))

    # --- Sensor validation ranges (section 15) ---
    PH_MIN: float = field(default_factory=lambda: _get_float("PH_MIN", 0))
    PH_MAX: float = field(default_factory=lambda: _get_float("PH_MAX", 14))
    TDS_MIN: float = field(default_factory=lambda: _get_float("TDS_MIN", 0))
    TDS_MAX: float = field(default_factory=lambda: _get_float("TDS_MAX", 5000))
    TURBIDITY_MIN: float = field(default_factory=lambda: _get_float("TURBIDITY_MIN", 0))
    TURBIDITY_MAX: float = field(default_factory=lambda: _get_float("TURBIDITY_MAX", 3000))
    TEMPERATURE_MIN: float = field(default_factory=lambda: _get_float("TEMPERATURE_MIN", -10))
    TEMPERATURE_MAX: float = field(default_factory=lambda: _get_float("TEMPERATURE_MAX", 60))
    HUMIDITY_MIN: float = field(default_factory=lambda: _get_float("HUMIDITY_MIN", 0))
    HUMIDITY_MAX: float = field(default_factory=lambda: _get_float("HUMIDITY_MAX", 100))

    # --- SQLite ---
    SQLITE_PATH: str = field(default_factory=lambda: _get_str(
        "SQLITE_PATH", str(_PROJECT_ROOT / "data" / "lakebot.db")
    ))

    # --- Upload behavior ---
    UPLOAD_BATCH_SIZE: int = field(default_factory=lambda: _get_int("UPLOAD_BATCH_SIZE", 20))
    # 0 == retry forever (never give up on an accepted reading, per RULE 13)
    UPLOAD_MAX_RETRIES: int = field(default_factory=lambda: _get_int("UPLOAD_MAX_RETRIES", 0))

    # --- Logging ---
    LOG_LEVEL: str = field(default_factory=lambda: _get_str("LOG_LEVEL", "INFO"))


# Singleton settings instance used throughout the application.
settings = Settings()
