"""SQLAlchemy ORM models.

Defines the complete (intentionally small) schema for this module:

    - :class:`Device`          — acquisition devices (Arduino units).
    - :class:`Sensor`          — configured sensor channels (metadata
                                   mirror of ``app/config/sensors.yaml``).
    - :class:`SensorReading`   — one row per validated sensor value per
                                   packet; the primary TimescaleDB
                                   hypertable.
    - :class:`ApplicationLog`  — lightweight application log records
                                   for monitoring/dashboarding.
    - :class:`SystemEvent`     — lightweight system/lifecycle events
                                   (connects, disconnects, migrations).

All models inherit from :class:`app.database.base.Base`. No
sensor-specific hardware models (e.g. DHT11, BMP180) are referenced
here - sensors are entirely data-driven via the ``sensors`` table,
itself populated from ``sensors.yaml``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.database.base import Base
from app.database.types import GUID


class Device(Base):
    """An acquisition device (e.g. an Arduino Uno) sending telemetry.

    Attributes:
        id: Primary key (UUID).
        device_name: Unique, human/firmware-reported device identifier
            (matches ``SensorPacket.device_id`` from the serial
            module).
        firmware_version: Last known firmware version reported by the
            device, if any.
        connection_status: Last known high-level connection status
            (free-form string, e.g. "connected", "disconnected",
            "unknown" - intentionally not coupled to the serial
            module's internal enum to keep this layer independent).
        last_seen_at: Timestamp of the most recent packet received
            from this device.
        created_at: Row creation timestamp.
        updated_at: Row last-update timestamp.
    """

    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    device_name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    firmware_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    connection_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    readings: Mapped[list["SensorReading"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Device id={self.id} device_name={self.device_name!r} status={self.connection_status!r}>"


class Sensor(Base):
    """Metadata describing a single configured sensor channel.

    This table mirrors (and persists) the generic sensor definitions
    from ``app/config/sensors.yaml`` so that historical readings
    remain interpretable even if the YAML file later changes. No
    hardware-specific sensor models are represented here.

    Attributes:
        id: Primary key (UUID).
        sensor_key: Unique canonical sensor identifier (matches
            ``SensorDefinition.sensor_name`` from the serial module's
            sensor registry, e.g. ``"dissolved_oxygen"``).
        display_name: Human friendly name.
        unit: Unit of measurement (e.g. "mg/L", "NTU", "C").
        sampling_interval_seconds: Expected sampling interval.
        minimum_value: Lowest physically valid reading.
        maximum_value: Highest physically valid reading.
        enabled: Whether this sensor channel is currently active.
        description: Short description of what the sensor measures.
        created_at: Row creation timestamp.
        updated_at: Row last-update timestamp.
    """

    __tablename__ = "sensors"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    sensor_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    sampling_interval_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    minimum_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    maximum_value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    readings: Mapped[list["SensorReading"]] = relationship(
        back_populates="sensor", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Sensor id={self.id} sensor_key={self.sensor_key!r} enabled={self.enabled}>"


class SensorReading(Base):
    """One validated sensor value from one packet.

    This is the primary, high-volume table - intended to be converted
    into a TimescaleDB hypertable (partitioned on ``timestamp``) via
    the Alembic migration in this module. At 15-20 sensors sampled
    every 5 seconds, 24/7, this table is expected to accumulate on the
    order of tens of millions of rows per year, so every query path
    here is expected to filter on ``timestamp`` and/or the indexed
    foreign keys.

    Attributes:
        id: Row identifier (UUID). Part of the composite primary key
            together with ``timestamp``, as required by TimescaleDB
            (every unique constraint on a hypertable must include the
            partitioning column).
        timestamp: The sensor reading's timestamp (the TimescaleDB
            partitioning column). This is the device-reported packet
            timestamp when parseable, otherwise the backend's local
            receipt time.
        device_id: Foreign key to :class:`Device`.
        sensor_id: Foreign key to :class:`Sensor`.
        value: The numeric reading value, or ``None`` for compound
            (e.g. GPS) or invalid/non-numeric readings.
        raw_value: JSON-encoded original value, used for compound
            readings (e.g. ``{"latitude": ..., "longitude": ...}``) or
            to preserve a non-numeric value for diagnostics.
        quality_score: Reserved for future quality scoring (0.0-1.0);
            not computed by this module.
        validation_status: One of ``"valid"``, ``"invalid"``,
            ``"out_of_range"``, ``"unknown_sensor"``, or
            ``"non_numeric"`` - mirrors the outcome from
            :mod:`app.serial.packet_validator`.
        packet_sequence: The originating packet's sequence number, if
            known - useful for correlating readings back to a single
            packet and for diagnosing gaps/duplicates.
        created_at: Row insertion timestamp (may differ slightly from
            ``timestamp`` due to processing/storage latency).
    """

    __tablename__ = "sensor_readings"
    # eager_defaults=False: this is the highest-volume table by far
    # (one row per sensor per ~5s packet, 24/7). Disabling the
    # automatic post-INSERT RETURNING fetch of server-generated
    # columns (created_at) avoids an unnecessary round trip on every
    # bulk insert and sidesteps a known SQLAlchemy 2.x edge case where
    # composite-primary-key sentinel matching for batched
    # INSERT...RETURNING can misbehave with custom column types (see
    # app/database/types.GUID) under heavy bulk_create() usage.
    __mapper_args__ = {"eager_defaults": False}
    __table_args__ = (
        PrimaryKeyConstraint("id", "timestamp", name="pk_sensor_readings"),
        Index("ix_sensor_readings_timestamp", "timestamp"),
        Index("ix_sensor_readings_device_timestamp", "device_id", "timestamp"),
        Index("ix_sensor_readings_sensor_timestamp", "sensor_id", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), default=uuid.uuid4, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    device_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    sensor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("sensors.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_value: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    quality_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="valid")
    packet_sequence: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    device: Mapped["Device"] = relationship(back_populates="readings")
    sensor: Mapped["Sensor"] = relationship(back_populates="readings")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"<SensorReading device_id={self.device_id} sensor_id={self.sensor_id} "
            f"timestamp={self.timestamp} value={self.value} status={self.validation_status!r}>"
        )


class ApplicationLog(Base):
    """Lightweight, queryable mirror of key application log lines.

    This is intentionally separate from the Loguru file sinks
    configured in :mod:`app.utils.logger` - it exists so a future
    dashboard can query "recent errors" without tailing log files.
    Not every log line needs to be written here; callers choose which
    events are worth persisting.

    Attributes:
        id: Primary key (auto-incrementing integer).
        timestamp: When the log entry was recorded.
        level: Log level string (e.g. "INFO", "WARNING", "ERROR").
        module: Originating module/component name.
        message: The log message.
        created_at: Row insertion timestamp.
    """

    __tablename__ = "application_logs"
    __table_args__ = (Index("ix_application_logs_timestamp", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    level: Mapped[str] = mapped_column(String(16), nullable=False)
    module: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<ApplicationLog id={self.id} level={self.level!r} module={self.module!r}>"


class SystemEvent(Base):
    """A discrete system/lifecycle event worth recording for monitoring.

    Examples: device connected/disconnected, reconnect occurred,
    migration applied, application startup/shutdown, unknown sensor
    field observed. Distinct from :class:`ApplicationLog` in that
    events are structured (``event_type`` + optional ``context`` JSON)
    rather than free-text log lines.

    Attributes:
        id: Primary key (auto-incrementing integer).
        timestamp: When the event occurred.
        event_type: Short machine-readable event category (e.g.
            ``"device_connected"``, ``"migration_applied"``).
        severity: One of ``"info"``, ``"warning"``, ``"error"``.
        source: Originating module/component name.
        message: Human readable description of the event.
        context: Optional structured JSON payload with extra details.
        created_at: Row insertion timestamp.
    """

    __tablename__ = "system_events"
    __table_args__ = (Index("ix_system_events_timestamp", "timestamp"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    source: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<SystemEvent id={self.id} event_type={self.event_type!r} severity={self.severity!r}>"
