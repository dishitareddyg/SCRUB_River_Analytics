"""Database service facade.

This is the single entry point future modules (and this module's own
serial-queue consumer) should use to talk to the database - none of
them need to know about SQLAlchemy sessions, the repository classes,
or the schema directly.

Every method opens its own short-lived session via
:func:`app.database.session.session_scope` (commit on success,
rollback on error, always closed), so :class:`DatabaseService` is
safe to share across threads: callers never hold a session across
calls.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, List, Optional

from sqlalchemy.orm import Session

from app.database.crud import (
    DeviceRepository,
    Page,
    SensorReadingRepository,
    SensorRepository,
    SystemEventRepository,
)
from app.database.models import Device, Sensor, SensorReading
from app.database.session import session_scope
from app.serial.sensor_packet import SensorPacket
from app.utils.exceptions import DatabaseError
from app.utils.logger import get_logger

logger = get_logger(__name__)

SessionScopeFactory = Callable[[], AbstractContextManager[Session]]

_VALIDATION_STATUS_VALID = "valid"
_VALIDATION_STATUS_INVALID = "invalid"


class DatabaseService:
    """High-level, thread-safe facade over the database repository layer.

    Instances hold no session state - every method call opens and
    closes its own session via the injected ``session_scope_factory``
    (defaulting to :func:`app.database.session.session_scope`), so a
    single :class:`DatabaseService` instance can safely be shared
    between the FastAPI request path and a background ingestion
    thread consuming packets from the serial module's queue.
    """

    def __init__(self, session_scope_factory: Optional[SessionScopeFactory] = None) -> None:
        """Initialize the service.

        Args:
            session_scope_factory: Zero-argument callable returning a
                context manager that yields a :class:`Session`.
                Defaults to :func:`app.database.session.session_scope`.
                Overridable for testing (e.g. to point at an
                in-memory SQLite database).
        """
        self._session_scope = session_scope_factory or session_scope

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_device(
        self,
        device_name: str,
        firmware_version: Optional[str] = None,
        connection_status: Optional[str] = None,
    ) -> Device:
        """Create or update a device record.

        Args:
            device_name: Unique device identifier.
            firmware_version: Firmware version to record, if known.
            connection_status: Connection status to record, if known.

        Returns:
            A detached copy of the created/updated :class:`Device`.
        """
        with self._session_scope() as session:
            device = DeviceRepository(session).upsert_by_name(
                device_name=device_name,
                firmware_version=firmware_version,
                connection_status=connection_status,
            )
            session.flush()
            session.expunge(device)
            return device

    def register_sensor(
        self,
        sensor_key: str,
        display_name: str,
        unit: Optional[str] = None,
        sampling_interval_seconds: Optional[int] = None,
        minimum_value: Optional[float] = None,
        maximum_value: Optional[float] = None,
        enabled: bool = True,
        description: Optional[str] = None,
    ) -> Sensor:
        """Create or update a sensor metadata record.

        Args:
            sensor_key: Unique canonical sensor identifier.
            display_name: Human friendly name.
            unit: Unit of measurement.
            sampling_interval_seconds: Expected sampling interval.
            minimum_value: Lowest physically valid reading.
            maximum_value: Highest physically valid reading.
            enabled: Whether the sensor channel is active.
            description: Short description of the sensor.

        Returns:
            A detached copy of the created/updated :class:`Sensor`.
        """
        with self._session_scope() as session:
            sensor = SensorRepository(session).upsert_by_key(
                sensor_key=sensor_key,
                display_name=display_name,
                unit=unit,
                sampling_interval_seconds=sampling_interval_seconds,
                minimum_value=minimum_value,
                maximum_value=maximum_value,
                enabled=enabled,
                description=description,
            )
            session.flush()
            session.expunge(sensor)
            return sensor

    def sync_sensor_registry(self, registry: Any) -> List[Sensor]:
        """Sync every sensor from a ``SensorRegistry`` into the database.

        Convenience method for startup: registers/updates a
        ``sensors`` row for every entry in
        ``app.serial.sensor_registry.SensorRegistry.all_sensors()``,
        keeping the persisted metadata in sync with ``sensors.yaml``.

        Args:
            registry: A ``SensorRegistry``-like object exposing
                ``all_sensors()`` (typed as ``Any`` to avoid a hard
                import-time dependency; duck-typed intentionally).

        Returns:
            The list of created/updated :class:`Sensor` records.
        """
        synced: List[Sensor] = []
        for definition in registry.all_sensors():
            synced.append(
                self.register_sensor(
                    sensor_key=definition.sensor_name,
                    display_name=definition.display_name,
                    unit=definition.unit,
                    sampling_interval_seconds=definition.sampling_interval,
                    minimum_value=definition.minimum_value,
                    maximum_value=definition.maximum_value,
                    enabled=definition.enabled,
                    description=definition.description,
                )
            )
        logger.info(f"Synced {len(synced)} sensors from the sensor registry.")
        return synced

    def get_device(self, device_name: str) -> Optional[Device]:
        """Fetch a device by name.

        Args:
            device_name: The device's unique name.

        Returns:
            A detached copy of the matching :class:`Device`, or
            ``None``.
        """
        with self._session_scope() as session:
            device = DeviceRepository(session).get_by_name(device_name)
            if device is not None:
                session.expunge(device)
            return device

    # ------------------------------------------------------------------
    # Writing readings
    # ------------------------------------------------------------------

    def save_sensor_reading(
        self,
        device_name: str,
        sensor_key: str,
        timestamp: datetime,
        value: Optional[float] = None,
        raw_value: Optional[Any] = None,
        validation_status: str = _VALIDATION_STATUS_VALID,
        packet_sequence: Optional[int] = None,
    ) -> Optional[SensorReading]:
        """Store a single sensor reading, resolving device/sensor by name.

        Args:
            device_name: The originating device's unique name. Must
                already be registered (see :meth:`register_device`).
            sensor_key: The sensor's canonical key. Must already be
                registered (see :meth:`register_sensor`).
            timestamp: The reading's timestamp.
            value: Numeric value, if applicable.
            raw_value: JSON-serializable original value, for compound
                or non-numeric readings.
            validation_status: Validation outcome string.
            packet_sequence: Originating packet sequence number.

        Returns:
            A detached copy of the created :class:`SensorReading`, or
            ``None`` if the device or sensor could not be resolved.
        """
        with self._session_scope() as session:
            device = DeviceRepository(session).get_by_name(device_name)
            sensor = SensorRepository(session).get_by_key(sensor_key)
            if device is None or sensor is None:
                logger.warning(
                    f"Cannot save reading: unknown device={device_name!r} or sensor={sensor_key!r}"
                )
                return None

            reading = SensorReadingRepository(session).create(
                device_id=device.id,
                sensor_id=sensor.id,
                timestamp=timestamp,
                value=value,
                raw_value=raw_value,
                validation_status=validation_status,
                packet_sequence=packet_sequence,
            )
            session.flush()
            session.expunge(reading)
            return reading

    def save_sensor_packet(self, packet: SensorPacket) -> int:
        """Persist every resolvable reading from a validated serial packet.

        This is the primary integration point with Module 2: the
        serial acquisition subsystem hands validated
        :class:`~app.serial.sensor_packet.SensorPacket` instances to
        this method (typically via
        :class:`app.database.ingestion_worker.IngestionWorker`
        consuming ``SerialManager.queue``), and this method:

            1. Upserts the originating device (name, last-seen time).
            2. For each resolved reading on the packet, resolves the
               matching ``sensors`` row and inserts one
               ``sensor_readings`` row.
            3. Records a ``system_events`` entry for any reading whose
               sensor could not be resolved (i.e. not yet registered
               via :meth:`register_sensor` /
               :meth:`sync_sensor_registry`), so the gap is visible
               without failing the whole packet.

        No derived parameters are calculated and no analytics are
        triggered here, per this module's scope.

        Args:
            packet: A validated :class:`SensorPacket` (typically one
                that passed
                :meth:`app.serial.packet_validator.PacketValidator.validate`).

        Returns:
            The number of individual sensor readings successfully
            stored.

        Raises:
            DatabaseError: If ``packet.device_id`` is missing (a
                packet cannot be stored without a device to attribute
                it to).
        """
        if not packet.device_id:
            raise DatabaseError("Cannot save a packet with no device_id.")

        received_at = packet.timestamp or packet.received_at

        with self._session_scope() as session:
            device_repo = DeviceRepository(session)
            sensor_repo = SensorRepository(session)
            reading_repo = SensorReadingRepository(session)
            event_repo = SystemEventRepository(session)

            device = device_repo.upsert_by_name(
                device_name=packet.device_id,
                last_seen_at=datetime.now(timezone.utc),
            )

            new_readings: List[SensorReading] = []

            for reading in packet.readings:
                if reading.sensor_name is None:
                    event_repo.create(
                        event_type="unknown_sensor_reading",
                        severity="warning",
                        source="database.save_sensor_packet",
                        message=(
                            f"Dropped reading for unrecognized field "
                            f"'{reading.field_name}' from device '{packet.device_id}'."
                        ),
                        context={"field_name": reading.field_name, "value": _jsonable(reading.value)},
                    )
                    continue

                sensor = sensor_repo.get_by_key(reading.sensor_name)
                if sensor is None:
                    event_repo.create(
                        event_type="unregistered_sensor_reading",
                        severity="warning",
                        source="database.save_sensor_packet",
                        message=(
                            f"Dropped reading for sensor '{reading.sensor_name}' "
                            f"(not yet registered) from device '{packet.device_id}'."
                        ),
                        context={"sensor_name": reading.sensor_name},
                    )
                    continue

                numeric_value: Optional[float]
                raw_value: Optional[Any]
                if isinstance(reading.value, (int, float)) and not isinstance(reading.value, bool):
                    numeric_value = float(reading.value)
                    raw_value = None
                else:
                    numeric_value = None
                    raw_value = _jsonable(reading.value)

                status = _VALIDATION_STATUS_VALID if reading.is_valid else _VALIDATION_STATUS_INVALID

                new_readings.append(
                    SensorReading(
                        device_id=device.id,
                        sensor_id=sensor.id,
                        timestamp=received_at,
                        value=numeric_value,
                        raw_value=raw_value,
                        validation_status=status,
                        packet_sequence=packet.sequence,
                    )
                )

            reading_repo.bulk_create(new_readings)
            stored_count = len(new_readings)
            session.flush()

        if stored_count:
            logger.info(
                f"Stored {stored_count} sensor readings for device '{packet.device_id}' "
                f"(sequence={packet.sequence})."
            )
        return stored_count

    # ------------------------------------------------------------------
    # Reading queries
    # ------------------------------------------------------------------

    def get_latest_readings(
        self,
        device_name: Optional[str] = None,
        sensor_key: Optional[str] = None,
        limit: int = 1,
    ) -> List[SensorReading]:
        """Fetch the most recent reading(s), optionally filtered.

        Args:
            device_name: Optional device name filter.
            sensor_key: Optional sensor key filter.
            limit: Maximum number of readings to return.

        Returns:
            Up to ``limit`` detached :class:`SensorReading` records,
            most recent first.
        """
        with self._session_scope() as session:
            device_id = None
            sensor_id = None

            if device_name is not None:
                device = DeviceRepository(session).get_by_name(device_name)
                if device is None:
                    return []
                device_id = device.id

            if sensor_key is not None:
                sensor = SensorRepository(session).get_by_key(sensor_key)
                if sensor is None:
                    return []
                sensor_id = sensor.id

            readings = SensorReadingRepository(session).get_latest_n(
                n=limit, device_id=device_id, sensor_id=sensor_id
            )
            for reading in readings:
                session.expunge(reading)
            return readings

    def get_sensor_history(
        self,
        sensor_key: str,
        start: datetime,
        end: datetime,
        device_name: Optional[str] = None,
        page: int = 1,
        page_size: int = 500,
    ) -> Page[SensorReading]:
        """Fetch historical readings for a sensor within a time range.

        Args:
            sensor_key: The sensor's canonical key.
            start: Inclusive start of the time range.
            end: Inclusive end of the time range.
            device_name: Optional device name filter.
            page: 1-indexed page number.
            page_size: Maximum records per page.

        Returns:
            A :class:`Page` of detached :class:`SensorReading`
            records. Returns an empty page if the sensor (or device,
            when specified) is not found.
        """
        with self._session_scope() as session:
            sensor = SensorRepository(session).get_by_key(sensor_key)
            if sensor is None:
                return Page(items=[], total=0, page=page, page_size=page_size)

            device_id = None
            if device_name is not None:
                device = DeviceRepository(session).get_by_name(device_name)
                if device is None:
                    return Page(items=[], total=0, page=page, page_size=page_size)
                device_id = device.id

            result = SensorReadingRepository(session).get_history(
                start=start,
                end=end,
                device_id=device_id,
                sensor_id=sensor.id,
                page=page,
                page_size=page_size,
            )
            for reading in result.items:
                session.expunge(reading)
            return result


def _jsonable(value: Any) -> Any:
    """Best-effort conversion of a value into a JSON-serializable form.

    Args:
        value: Any value that may need to be stored in a JSON column.

    Returns:
        The value unchanged if it is already JSON-serializable
        (dict/list/str/int/float/bool/None), otherwise its string
        representation.
    """
    if value is None or isinstance(value, (dict, list, str, int, float, bool)):
        return value
    return str(value)


@lru_cache
def get_database_service() -> DatabaseService:
    """Return a cached, process-wide :class:`DatabaseService` instance.

    Future FastAPI routes can depend on this the same way
    :func:`app.config.settings.get_settings` is used, e.g.::

        from fastapi import Depends
        from app.database.service import get_database_service, DatabaseService

        @router.get("/example")
        def example(db: DatabaseService = Depends(get_database_service)):
            ...

    Returns:
        The singleton :class:`DatabaseService`.
    """
    return DatabaseService()
