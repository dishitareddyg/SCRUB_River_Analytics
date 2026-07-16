"""Application-wide constants.

Values here are truly static (not environment dependent). Anything
that could change between deployments belongs in
:mod:`app.config.settings` instead.
"""

from enum import Enum


API_VERSION_1: str = "v1"
"""Identifier for the first API version."""

OPENAPI_TITLE: str = "River Intelligence Platform API"
"""Title shown in the generated OpenAPI/Swagger documentation."""

OPENAPI_DESCRIPTION: str = (
    "Backend service for the River Intelligence Platform (RIP). "
    "Provides ingestion, storage, analytics, machine learning, "
    "prediction and reporting APIs for river water-quality "
    "monitoring hardware built around an Arduino Uno."
)
"""Description shown in the generated OpenAPI/Swagger documentation."""

DEFAULT_DATE_FORMAT: str = "%Y-%m-%d"
"""Standard date format used across the backend."""

DEFAULT_DATETIME_FORMAT: str = "%Y-%m-%d %H:%M:%S"
"""Standard datetime format used across the backend."""

LOG_ROTATION: str = "00:00"
"""Loguru rotation trigger: rotate daily at midnight."""

LOG_RETENTION: str = "30 days"
"""Loguru retention policy for rotated log files."""

LOG_APPLICATION_FILENAME: str = "application.log"
"""Filename used for the general application log."""

LOG_ERROR_FILENAME: str = "error.log"
"""Filename used for the error-only log."""


class Environment(str, Enum):
    """Supported application runtime environments."""

    DEVELOPMENT = "development"
    TESTING = "testing"
    PRODUCTION = "production"


class SensorCategory(str, Enum):
    """High level categories of sensors the platform is designed for.

    NOTE: This enum only names *categories* the system is prepared to
    support. It intentionally does NOT reference any specific sensor
    hardware model (e.g. DHT11, BMP180, DS18B20) - those remain
    implementation details of the future firmware/serial modules and
    may be referenced only in comments.
    """

    DISSOLVED_OXYGEN = "dissolved_oxygen"
    PH = "ph"
    CONDUCTIVITY = "conductivity"
    ORP = "orp"
    TURBIDITY = "turbidity"
    WATER_TEMPERATURE = "water_temperature"
    AIR_TEMPERATURE = "air_temperature"
    HUMIDITY = "humidity"
    BAROMETRIC_PRESSURE = "barometric_pressure"
    WATER_LEVEL = "water_level"
    RIVER_DEPTH = "river_depth"
    GPS = "gps"
    RAINFALL = "rainfall"
    WIND_SPEED = "wind_speed"
    PAR = "par"
