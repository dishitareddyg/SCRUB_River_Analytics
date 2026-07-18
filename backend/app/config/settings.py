"""Centralized application configuration.

This module defines a single source of truth for all configuration
values used across the River Intelligence Platform backend. All
values are loaded from environment variables (via a ``.env`` file in
development) using ``pydantic-settings``. Nothing in this project
should hardcode configuration values outside of this module.

Future modules (serial communication, analytics, ML, reporting) MUST
read their configuration from :func:`get_settings` rather than
defining their own environment parsing logic.
"""

from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables.

    Attributes:
        app_name: Human readable application name.
        app_version: Semantic version of the backend service.
        debug: Enables verbose/debug behavior (should be False in
            production).
        environment: Deployment environment name (e.g. "development",
            "production", "testing").

        api_host: Host/interface the FastAPI server binds to.
        api_port: Port the FastAPI server binds to.
        api_prefix: Base path prefix for all versioned API routes.
        api_v1_prefix: Path prefix for version 1 of the API.
        cors_origins: List of allowed CORS origins for the dashboard.

        database_url: Full SQLAlchemy-compatible database connection
            string (PostgreSQL/TimescaleDB).
        database_port: Port used by the database server.
        database_pool_size: Size of the SQLAlchemy connection pool.
        database_max_overflow: Max overflow connections allowed above
            the pool size.
        database_echo: Whether SQLAlchemy should echo raw SQL (debug
            only).

        serial_com_port: Serial COM port the Arduino Uno is connected
            to (e.g. "COM3" on Windows or "/dev/ttyUSB0" on Linux).
            Reserved for the future serial communication module.
        serial_baud_rate: Baud rate used for serial communication.
            Reserved for the future serial communication module.
        sampling_interval_seconds: Default sensor sampling interval,
            in seconds. Reserved for future sensor modules.
        serial_auto_detect: Whether to auto-detect the Arduino's COM
            port when ``serial_com_port`` is set to ``"auto"``.
        serial_connect_timeout_seconds: Timeout, in seconds, allowed
            when opening the serial port.
        serial_read_timeout_seconds: Timeout, in seconds, for a single
            blocking serial read call.
        serial_reconnect_delay_seconds: Base delay, in seconds, before
            attempting to reconnect after a communication failure.
        serial_max_reconnect_delay_seconds: Upper bound, in seconds,
            for the reconnect backoff delay.
        serial_max_line_bytes: Maximum accepted length, in bytes, of a
            single serial line before it is discarded as corrupted.
        serial_queue_max_size: Maximum number of validated packets
            buffered in the in-memory acquisition queue.

        dashboard_refresh_interval_seconds: Suggested refresh interval
            for the React dashboard's live views.

        log_folder: Directory where rotating log files are written.
        log_level: Minimum log level emitted to the console/handlers.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------
    # Application metadata
    # ------------------------------------------------------------------
    app_name: str = Field(default="River Intelligence Platform")
    app_version: str = Field(default="0.1.0")
    debug: bool = Field(default=False)
    environment: str = Field(default="development")

    # ------------------------------------------------------------------
    # API / server configuration
    # ------------------------------------------------------------------
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    api_prefix: str = Field(default="/api")
    api_v1_prefix: str = Field(default="/api/v1")
    cors_origins: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # ------------------------------------------------------------------
    # Database configuration (PostgreSQL / TimescaleDB)
    # ------------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg2://postgres:postgres@localhost:5432/river_intelligence"
    )
    database_port: int = Field(default=5432)
    database_pool_size: int = Field(default=5)
    database_max_overflow: int = Field(default=10)
    database_echo: bool = Field(default=False)

    # ------------------------------------------------------------------
    # Serial / Arduino configuration (reserved for future module)
    # ------------------------------------------------------------------
    serial_com_port: str = Field(default="COM3")
    serial_baud_rate: int = Field(default=9600)
    sampling_interval_seconds: int = Field(default=5)

    # Additional serial acquisition tuning, consumed by app/serial/.
    serial_auto_detect: bool = Field(
        default=True,
        description=(
            "If true, auto-detect the Arduino's COM port when "
            "serial_com_port is left as 'auto'; otherwise always use "
            "serial_com_port as configured."
        ),
    )
    serial_connect_timeout_seconds: float = Field(default=2.0)
    serial_read_timeout_seconds: float = Field(default=1.0)
    serial_reconnect_delay_seconds: float = Field(default=5.0)
    serial_max_reconnect_delay_seconds: float = Field(default=30.0)
    serial_max_line_bytes: int = Field(default=4096)
    serial_queue_max_size: int = Field(default=500)

    # ------------------------------------------------------------------
    # Dashboard configuration
    # ------------------------------------------------------------------
    dashboard_refresh_interval_seconds: int = Field(default=5)

    # ------------------------------------------------------------------
    # Logging configuration
    # ------------------------------------------------------------------
    log_folder: str = Field(default="logs")
    log_level: str = Field(default="INFO")

    # ------------------------------------------------------------------
    # AI Decision Support Engine configuration (app/ml)
    # ------------------------------------------------------------------
    ml_model_dir: str = Field(
        default="app/ml/artifacts",
        description="Directory where trained models are versioned and persisted via joblib.",
    )
    ml_min_training_samples: int = Field(
        default=30,
        description=(
            "Minimum number of usable historical data points required before a model may be "
            "trained; below this, inference endpoints report INSUFFICIENT_DATA instead of "
            "training on too little data."
        ),
    )
    ml_training_window_days: int = Field(
        default=90,
        description="Default lookback window, in days, used to assemble training datasets.",
    )
    ml_resample_frequency: str = Field(
        default="1h",
        description="Pandas offset alias used to resample multi-sensor series onto a shared time axis.",
    )
    ml_anomaly_contamination: float = Field(
        default=0.05,
        description="Expected proportion of anomalous points, passed to IsolationForest.",
    )
    ml_random_state: int = Field(
        default=42,
        description="Random seed used by every ML estimator, for reproducible training runs.",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, value: object) -> object:
        """Allow CORS origins to be provided as a comma-separated string.

        Args:
            value: Raw value from the environment. Either a comma
                separated string (e.g. "http://a,http://b") or an
                already-parsed list.

        Returns:
            A list of origin strings.
        """
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _normalize_log_level(cls, value: object) -> object:
        """Uppercase the configured log level.

        Args:
            value: Raw log level string from the environment.

        Returns:
            The uppercased log level string.
        """
        if isinstance(value, str):
            return value.upper()
        return value


@lru_cache
def get_settings() -> Settings:
    """Return a cached, process-wide :class:`Settings` instance.

    Using ``lru_cache`` ensures the ``.env`` file is parsed only once
    and that every part of the application shares the exact same
    configuration object.

    Returns:
        The singleton :class:`Settings` instance.
    """
    return Settings()
