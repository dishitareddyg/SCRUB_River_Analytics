"""Schemas for system status/info (``/system``)."""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class ComponentStatus(str, Enum):
    """A component's coarse health classification.

    Attributes:
        OK: The component is functioning normally.
        DEGRADED: The component is reachable/running but impaired.
        DISCONNECTED: The component (e.g. the serial acquisition
            link) is not currently connected.
    """

    OK = "ok"
    DEGRADED = "degraded"
    DISCONNECTED = "disconnected"


class SystemHealthData(BaseModel):
    """Payload for ``GET /system/health``.

    Attributes:
        application_status: Overall application process status.
        database_status: Database connectivity status.
        serial_connection_status: Live status of the serial
            acquisition subsystem's connection to the Arduino (see
            :class:`app.serial.status.ConnectionStatus`); reports
            ``"disconnected"`` when the acquisition subsystem has not
            been started for this process.
        version: The running application's semantic version.
        uptime_seconds: Seconds since this API process started.
    """

    application_status: ComponentStatus = Field(..., examples=[ComponentStatus.OK])
    database_status: ComponentStatus = Field(..., examples=[ComponentStatus.OK])
    serial_connection_status: str = Field(..., examples=["disconnected"])
    version: str = Field(..., examples=["0.1.0"])
    uptime_seconds: float = Field(..., examples=[128.4])


class SensorSummary(BaseModel):
    """A brief summary of one configured sensor channel.

    Attributes:
        sensor_name: Canonical machine-readable sensor identifier.
        display_name: Human friendly sensor name.
        unit: Unit of measurement.
        enabled: Whether this sensor channel is currently active.
    """

    sensor_name: str = Field(..., examples=["dissolved_oxygen"])
    display_name: str = Field(..., examples=["Dissolved Oxygen"])
    unit: Optional[str] = Field(None, examples=["mg/L"])
    enabled: bool = Field(..., examples=[True])


class SystemInfoData(BaseModel):
    """Payload for ``GET /system/info``.

    Attributes:
        application_name: Configured application name.
        application_version: Configured application semantic version.
        environment: Runtime environment (e.g. ``"development"``).
        connected_device: The last known connected device's
            identifier, or ``None`` if no device has ever connected in
            this process.
        firmware_version: The last known firmware version reported by
            the connected device, or ``None`` if unknown.
        configured_sensors: Every sensor channel configured in
            ``sensors.yaml``, enabled or not.
        database_type: The configured database backend (e.g.
            ``"postgresql"``), parsed from the configured connection
            string.
    """

    application_name: str = Field(..., examples=["River Intelligence Platform"])
    application_version: str = Field(..., examples=["0.1.0"])
    environment: str = Field(..., examples=["development"])
    connected_device: Optional[str] = Field(None, examples=["river-bot-01"])
    firmware_version: Optional[str] = Field(None, examples=["1.2.0"])
    configured_sensors: List[SensorSummary] = Field(default_factory=list)
    database_type: str = Field(..., examples=["postgresql"])
