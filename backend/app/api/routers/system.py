"""System status and info endpoints (``/system``).

Read-only reporting only: overall process health, database
connectivity, serial acquisition connection status, and static
deployment info (version, connected device, configured sensors,
database backend). Performs no analytics and modifies no state.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, Depends

from app.api.dependencies import (
    get_serial_manager_dependency,
    get_sensor_registry_dependency,
    get_settings_dependency,
    get_uptime_seconds,
)
from app.api.responses import SystemHealthApiResponse, SystemInfoApiResponse, success
from app.api.schemas.system import ComponentStatus, SensorSummary, SystemHealthData, SystemInfoData
from app.config.settings import Settings
from app.database.db import check_database_connection
from app.serial.sensor_registry import SensorRegistry
from app.serial.serial_manager import SerialManager

router = APIRouter(tags=["System"])


def _database_type(database_url: str) -> str:
    """Extract a short database backend name from a connection string.

    Args:
        database_url: A SQLAlchemy-style connection string, e.g.
            ``"postgresql+psycopg2://user:pass@host/db"``.

    Returns:
        The scheme's backend component (e.g. ``"postgresql"``), or
        ``"unknown"`` if it cannot be parsed.
    """
    scheme = urlsplit(database_url).scheme
    if not scheme:
        return "unknown"
    return scheme.split("+", 1)[0]


@router.get(
    "/health",
    response_model=SystemHealthApiResponse,
    summary="System health check",
    description=(
        "Reports overall application status, database connectivity, "
        "serial acquisition connection status, application version, "
        "and process uptime. Always returns HTTP 200 - clients should "
        "inspect the individual status fields, since a hard failure "
        "here would defeat the purpose of a health check."
    ),
    responses={
        200: {
            "description": "Health snapshot retrieved.",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "message": "System is healthy.",
                        "data": {
                            "application_status": "ok",
                            "database_status": "ok",
                            "serial_connection_status": "disconnected",
                            "version": "0.1.0",
                            "uptime_seconds": 128.4,
                        },
                        "meta": {"api_version": "v1", "timestamp": "2026-07-14T09:30:00Z"},
                    }
                }
            },
        }
    },
)
def get_system_health(
    settings: Settings = Depends(get_settings_dependency),
    serial_manager: SerialManager = Depends(get_serial_manager_dependency),
) -> SystemHealthApiResponse:
    """Report application, database, and serial connection health.

    Args:
        settings: Injected application settings.
        serial_manager: Injected serial acquisition manager (used
            read-only, for its status snapshot).

    Returns:
        A :class:`~app.api.responses.SystemHealthApiResponse`.
    """
    database_ok = check_database_connection()
    serial_status = serial_manager.status.snapshot().status.value

    data = SystemHealthData(
        application_status=ComponentStatus.OK,
        database_status=ComponentStatus.OK if database_ok else ComponentStatus.DEGRADED,
        serial_connection_status=serial_status,
        version=settings.app_version,
        uptime_seconds=get_uptime_seconds(),
    )
    message = "System is healthy." if database_ok else "System is degraded: database unreachable."
    return success(data, message)


@router.get(
    "/info",
    response_model=SystemInfoApiResponse,
    summary="System and deployment info",
    description=(
        "Reports static/slow-changing deployment info: application "
        "version, the last known connected device and firmware "
        "version (if any device has connected in this process), "
        "every configured sensor channel, and the configured database "
        "backend."
    ),
)
def get_system_info(
    settings: Settings = Depends(get_settings_dependency),
    serial_manager: SerialManager = Depends(get_serial_manager_dependency),
    registry: SensorRegistry = Depends(get_sensor_registry_dependency),
) -> SystemInfoApiResponse:
    """Report application version, connected device, and configured sensors.

    Args:
        settings: Injected application settings.
        serial_manager: Injected serial acquisition manager (used
            read-only, for its device snapshot).
        registry: Injected sensor registry.

    Returns:
        A :class:`~app.api.responses.SystemInfoApiResponse`.
    """
    device_state = serial_manager.devices.snapshot()

    sensors = [
        SensorSummary(
            sensor_name=definition.sensor_name,
            display_name=definition.display_name,
            unit=definition.unit,
            enabled=definition.enabled,
        )
        for definition in registry.all_sensors()
    ]

    data = SystemInfoData(
        application_name=settings.app_name,
        application_version=settings.app_version,
        environment=settings.environment,
        connected_device=device_state.device_id,
        firmware_version=device_state.firmware_version,
        configured_sensors=sensors,
        database_type=_database_type(settings.database_url),
    )
    return success(data, "System information retrieved.")
