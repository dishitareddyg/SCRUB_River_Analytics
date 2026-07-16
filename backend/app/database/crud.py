"""Repository layer (CRUD + query helpers) for all database models.

Implements the Repository pattern: each repository wraps a single
SQLAlchemy :class:`~sqlalchemy.orm.Session` (supplied by the caller,
per the Dependency Injection style used throughout this project) and
exposes create/read/update/delete plus the domain-specific query
methods required by this module (pagination, time-range queries,
latest value, latest N values).

Repositories never open or close sessions themselves - that is the
responsibility of the caller (typically
:func:`app.database.session.get_db` in a request, or
:func:`app.database.session.session_scope` in a background
thread/script), which keeps repositories trivially testable against
any session, including an in-memory SQLite session in unit tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, List, Optional, Sequence, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database.models import ApplicationLog, Device, Sensor, SensorReading, SystemEvent
from app.utils.exceptions import DatabaseError
from app.utils.logger import get_logger

logger = get_logger(__name__)

ModelT = TypeVar("ModelT")


@dataclass
class Page(Generic[ModelT]):
    """A single page of paginated query results.

    Attributes:
        items: The records on this page.
        total: Total number of matching records across all pages.
        page: 1-indexed page number returned.
        page_size: Maximum number of records requested per page.
    """

    items: List[ModelT]
    total: int
    page: int
    page_size: int

    @property
    def total_pages(self) -> int:
        """Total number of pages available for this page size.

        Returns:
            The number of pages, at least 1.
        """
        if self.page_size <= 0:
            return 1
        return max(1, (self.total + self.page_size - 1) // self.page_size)


class _BaseRepository:
    """Shared helpers for all repositories.

    Attributes:
        session: The SQLAlchemy session this repository operates on.
    """

    def __init__(self, session: Session) -> None:
        """Initialize the repository.

        Args:
            session: An active SQLAlchemy session. Its lifecycle
                (commit/rollback/close) is managed by the caller.
        """
        self.session = session

    def _flush(self) -> None:
        """Flush pending changes, translating SQLAlchemy errors.

        Raises:
            DatabaseError: If flushing fails (e.g. a constraint
                violation).
        """
        try:
            self.session.flush()
        except SQLAlchemyError as exc:
            logger.error(f"Database flush failed: {exc}")
            raise DatabaseError(f"Database operation failed: {exc}") from exc


class DeviceRepository(_BaseRepository):
    """CRUD and query operations for :class:`Device` records."""

    def create(
        self,
        device_name: str,
        firmware_version: Optional[str] = None,
        connection_status: str = "unknown",
    ) -> Device:
        """Create a new device record.

        Args:
            device_name: Unique device identifier.
            firmware_version: Reported firmware version, if known.
            connection_status: Initial connection status.

        Returns:
            The newly created, flushed :class:`Device`.

        Raises:
            DatabaseError: If the insert fails (e.g. duplicate name).
        """
        device = Device(
            device_name=device_name,
            firmware_version=firmware_version,
            connection_status=connection_status,
        )
        self.session.add(device)
        self._flush()
        logger.info(f"Registered new device: {device_name}")
        return device

    def get_by_id(self, device_id: uuid.UUID) -> Optional[Device]:
        """Fetch a device by primary key.

        Args:
            device_id: The device's UUID.

        Returns:
            The matching :class:`Device`, or ``None``.
        """
        return self.session.get(Device, device_id)

    def get_by_name(self, device_name: str) -> Optional[Device]:
        """Fetch a device by its unique name.

        Args:
            device_name: The device's unique name.

        Returns:
            The matching :class:`Device`, or ``None``.
        """
        stmt = select(Device).where(Device.device_name == device_name)
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert_by_name(
        self,
        device_name: str,
        firmware_version: Optional[str] = None,
        connection_status: Optional[str] = None,
        last_seen_at: Optional[datetime] = None,
    ) -> Device:
        """Create the device if absent, otherwise update its metadata.

        Args:
            device_name: Unique device identifier.
            firmware_version: Firmware version to record, if provided.
            connection_status: Connection status to record, if
                provided.
            last_seen_at: Timestamp to record as the last-seen time,
                if provided.

        Returns:
            The created or updated :class:`Device`.
        """
        device = self.get_by_name(device_name)
        if device is None:
            device = Device(
                device_name=device_name,
                firmware_version=firmware_version,
                connection_status=connection_status or "unknown",
                last_seen_at=last_seen_at,
            )
            self.session.add(device)
            logger.info(f"Registered new device: {device_name}")
        else:
            if firmware_version is not None:
                device.firmware_version = firmware_version
            if connection_status is not None:
                device.connection_status = connection_status
            if last_seen_at is not None:
                device.last_seen_at = last_seen_at
        self._flush()
        return device

    def list_all(self, page: int = 1, page_size: int = 50) -> Page[Device]:
        """List all devices, paginated.

        Args:
            page: 1-indexed page number.
            page_size: Maximum records per page.

        Returns:
            A :class:`Page` of :class:`Device` records ordered by
            name.
        """
        return _paginate(self.session, select(Device).order_by(Device.device_name), page, page_size)

    def update_status(self, device_id: uuid.UUID, connection_status: str) -> Optional[Device]:
        """Update a device's connection status.

        Args:
            device_id: The device's UUID.
            connection_status: The new connection status string.

        Returns:
            The updated :class:`Device`, or ``None`` if not found.
        """
        device = self.get_by_id(device_id)
        if device is None:
            return None
        device.connection_status = connection_status
        self._flush()
        return device

    def delete(self, device_id: uuid.UUID) -> bool:
        """Delete a device (and, via cascade, its readings).

        Args:
            device_id: The device's UUID.

        Returns:
            ``True`` if a device was deleted, ``False`` if not found.
        """
        device = self.get_by_id(device_id)
        if device is None:
            return False
        self.session.delete(device)
        self._flush()
        logger.info(f"Deleted device: {device.device_name}")
        return True


class SensorRepository(_BaseRepository):
    """CRUD and query operations for :class:`Sensor` records."""

    def create(
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
        """Create a new sensor metadata record.

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
            The newly created, flushed :class:`Sensor`.
        """
        sensor = Sensor(
            sensor_key=sensor_key,
            display_name=display_name,
            unit=unit,
            sampling_interval_seconds=sampling_interval_seconds,
            minimum_value=minimum_value,
            maximum_value=maximum_value,
            enabled=enabled,
            description=description,
        )
        self.session.add(sensor)
        self._flush()
        logger.info(f"Registered new sensor: {sensor_key}")
        return sensor

    def get_by_id(self, sensor_id: uuid.UUID) -> Optional[Sensor]:
        """Fetch a sensor by primary key.

        Args:
            sensor_id: The sensor's UUID.

        Returns:
            The matching :class:`Sensor`, or ``None``.
        """
        return self.session.get(Sensor, sensor_id)

    def get_by_key(self, sensor_key: str) -> Optional[Sensor]:
        """Fetch a sensor by its unique canonical key.

        Args:
            sensor_key: The sensor's canonical key (e.g.
                ``"dissolved_oxygen"``).

        Returns:
            The matching :class:`Sensor`, or ``None``.
        """
        stmt = select(Sensor).where(Sensor.sensor_key == sensor_key)
        return self.session.execute(stmt).scalar_one_or_none()

    def upsert_by_key(
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
        """Create the sensor if absent, otherwise update its metadata.

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
            The created or updated :class:`Sensor`.
        """
        sensor = self.get_by_key(sensor_key)
        if sensor is None:
            sensor = Sensor(
                sensor_key=sensor_key,
                display_name=display_name,
                unit=unit,
                sampling_interval_seconds=sampling_interval_seconds,
                minimum_value=minimum_value,
                maximum_value=maximum_value,
                enabled=enabled,
                description=description,
            )
            self.session.add(sensor)
            logger.info(f"Registered new sensor: {sensor_key}")
        else:
            sensor.display_name = display_name
            sensor.unit = unit
            sensor.sampling_interval_seconds = sampling_interval_seconds
            sensor.minimum_value = minimum_value
            sensor.maximum_value = maximum_value
            sensor.enabled = enabled
            sensor.description = description
        self._flush()
        return sensor

    def list_all(self, page: int = 1, page_size: int = 50) -> Page[Sensor]:
        """List all sensors, paginated.

        Args:
            page: 1-indexed page number.
            page_size: Maximum records per page.

        Returns:
            A :class:`Page` of :class:`Sensor` records ordered by key.
        """
        return _paginate(self.session, select(Sensor).order_by(Sensor.sensor_key), page, page_size)

    def list_enabled(self) -> Sequence[Sensor]:
        """Return all sensors currently marked as enabled.

        Returns:
            A sequence of enabled :class:`Sensor` records.
        """
        stmt = select(Sensor).where(Sensor.enabled.is_(True)).order_by(Sensor.sensor_key)
        return self.session.execute(stmt).scalars().all()

    def delete(self, sensor_id: uuid.UUID) -> bool:
        """Delete a sensor (and, via cascade, its readings).

        Args:
            sensor_id: The sensor's UUID.

        Returns:
            ``True`` if a sensor was deleted, ``False`` if not found.
        """
        sensor = self.get_by_id(sensor_id)
        if sensor is None:
            return False
        self.session.delete(sensor)
        self._flush()
        logger.info(f"Deleted sensor: {sensor.sensor_key}")
        return True


class SensorReadingRepository(_BaseRepository):
    """CRUD and query operations for :class:`SensorReading` records."""

    def create(
        self,
        device_id: uuid.UUID,
        sensor_id: uuid.UUID,
        timestamp: datetime,
        value: Optional[float] = None,
        raw_value: Optional[object] = None,
        quality_score: Optional[float] = None,
        validation_status: str = "valid",
        packet_sequence: Optional[int] = None,
    ) -> SensorReading:
        """Insert a single sensor reading.

        Args:
            device_id: The originating device's UUID.
            sensor_id: The sensor's UUID.
            timestamp: The reading's timestamp.
            value: Numeric value, if applicable.
            raw_value: JSON-serializable original value (for compound
                or non-numeric readings).
            quality_score: Reserved for future quality scoring.
            validation_status: Validation outcome string.
            packet_sequence: Originating packet sequence number.

        Returns:
            The newly created, flushed :class:`SensorReading`.
        """
        reading = SensorReading(
            device_id=device_id,
            sensor_id=sensor_id,
            timestamp=timestamp,
            value=value,
            raw_value=raw_value,
            quality_score=quality_score,
            validation_status=validation_status,
            packet_sequence=packet_sequence,
        )
        self.session.add(reading)
        self._flush()
        return reading

    def bulk_create(self, readings: Sequence[SensorReading]) -> List[SensorReading]:
        """Insert multiple sensor readings in a single flush.

        Args:
            readings: Unpersisted :class:`SensorReading` instances to
                insert together (e.g. all readings from one packet).

        Returns:
            The same list of readings, now persisted and flushed.
        """
        if not readings:
            return []
        self.session.add_all(readings)
        self._flush()
        return list(readings)

    def get_latest(self, device_id: uuid.UUID, sensor_id: uuid.UUID) -> Optional[SensorReading]:
        """Fetch the single most recent reading for a device+sensor pair.

        Args:
            device_id: The device's UUID.
            sensor_id: The sensor's UUID.

        Returns:
            The most recent :class:`SensorReading`, or ``None``.
        """
        stmt = (
            select(SensorReading)
            .where(SensorReading.device_id == device_id, SensorReading.sensor_id == sensor_id)
            .order_by(SensorReading.timestamp.desc())
            .limit(1)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_latest_n(
        self,
        n: int,
        device_id: Optional[uuid.UUID] = None,
        sensor_id: Optional[uuid.UUID] = None,
    ) -> List[SensorReading]:
        """Fetch the N most recent readings, optionally filtered.

        Args:
            n: Maximum number of readings to return.
            device_id: Optional device filter.
            sensor_id: Optional sensor filter.

        Returns:
            Up to ``n`` :class:`SensorReading` records, most recent
            first.
        """
        stmt = select(SensorReading).order_by(SensorReading.timestamp.desc()).limit(n)
        if device_id is not None:
            stmt = stmt.where(SensorReading.device_id == device_id)
        if sensor_id is not None:
            stmt = stmt.where(SensorReading.sensor_id == sensor_id)
        return list(self.session.execute(stmt).scalars().all())

    def get_history(
        self,
        start: datetime,
        end: datetime,
        device_id: Optional[uuid.UUID] = None,
        sensor_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 500,
    ) -> Page[SensorReading]:
        """Fetch readings within a time range, paginated.

        Args:
            start: Inclusive start of the time range.
            end: Inclusive end of the time range.
            device_id: Optional device filter.
            sensor_id: Optional sensor filter.
            page: 1-indexed page number.
            page_size: Maximum records per page.

        Returns:
            A :class:`Page` of :class:`SensorReading` records ordered
            chronologically (oldest first) within the requested page.
        """
        stmt = select(SensorReading).where(
            SensorReading.timestamp >= start, SensorReading.timestamp <= end
        )
        if device_id is not None:
            stmt = stmt.where(SensorReading.device_id == device_id)
        if sensor_id is not None:
            stmt = stmt.where(SensorReading.sensor_id == sensor_id)
        stmt = stmt.order_by(SensorReading.timestamp.asc())
        return _paginate(self.session, stmt, page, page_size)

    def count_in_range(
        self,
        start: datetime,
        end: datetime,
        device_id: Optional[uuid.UUID] = None,
        sensor_id: Optional[uuid.UUID] = None,
    ) -> int:
        """Count readings within an inclusive time range without fetching rows.

        Args:
            start: Inclusive start of the time range.
            end: Inclusive end of the time range.
            device_id: Optional device filter.
            sensor_id: Optional sensor filter.

        Returns:
            The number of matching readings.
        """
        stmt = select(func.count()).select_from(SensorReading).where(
            SensorReading.timestamp >= start, SensorReading.timestamp <= end
        )
        if device_id is not None:
            stmt = stmt.where(SensorReading.device_id == device_id)
        if sensor_id is not None:
            stmt = stmt.where(SensorReading.sensor_id == sensor_id)
        return self.session.execute(stmt).scalar_one()

    def count_before(
        self,
        cutoff: datetime,
        device_id: Optional[uuid.UUID] = None,
        sensor_id: Optional[uuid.UUID] = None,
    ) -> int:
        """Count readings strictly before ``cutoff`` (``timestamp < cutoff``).

        Mirrors :meth:`delete_older_than`'s exclusive semantics, so
        retention tooling can preview exactly how many rows a purge
        would affect before running it.

        Args:
            cutoff: Only readings with ``timestamp < cutoff`` count.
            device_id: Optional device filter.
            sensor_id: Optional sensor filter.

        Returns:
            The number of matching readings.
        """
        stmt = select(func.count()).select_from(SensorReading).where(
            SensorReading.timestamp < cutoff
        )
        if device_id is not None:
            stmt = stmt.where(SensorReading.device_id == device_id)
        if sensor_id is not None:
            stmt = stmt.where(SensorReading.sensor_id == sensor_id)
        return self.session.execute(stmt).scalar_one()

    def get_before(
        self,
        cutoff: datetime,
        device_id: Optional[uuid.UUID] = None,
        sensor_id: Optional[uuid.UUID] = None,
        page: int = 1,
        page_size: int = 500,
    ) -> Page[SensorReading]:
        """Fetch readings strictly before ``cutoff``, paginated.

        Mirrors :meth:`delete_older_than`'s exclusive semantics (``timestamp
        < cutoff``), intended for retention/archival tooling that
        previews or exports exactly what a subsequent
        :meth:`delete_older_than` call would remove.

        Args:
            cutoff: Only readings with ``timestamp < cutoff`` are
                returned.
            device_id: Optional device filter.
            sensor_id: Optional sensor filter.
            page: 1-indexed page number.
            page_size: Maximum records per page.

        Returns:
            A :class:`Page` of :class:`SensorReading` records ordered
            chronologically (oldest first).
        """
        stmt = select(SensorReading).where(SensorReading.timestamp < cutoff)
        if device_id is not None:
            stmt = stmt.where(SensorReading.device_id == device_id)
        if sensor_id is not None:
            stmt = stmt.where(SensorReading.sensor_id == sensor_id)
        stmt = stmt.order_by(SensorReading.timestamp.asc())
        return _paginate(self.session, stmt, page, page_size)

    def delete_older_than(self, cutoff: datetime) -> int:
        """Delete all readings strictly older than ``cutoff``.

        Intended for use by :mod:`app.database.retention`, not called
        automatically by this module.

        Args:
            cutoff: Readings with ``timestamp < cutoff`` are deleted.

        Returns:
            The number of rows deleted.
        """
        stmt = delete(SensorReading).where(SensorReading.timestamp < cutoff)
        result = self.session.execute(stmt)
        self._flush()
        count = result.rowcount or 0
        if count:
            logger.info(f"Deleted {count} sensor readings older than {cutoff.isoformat()}")
        return count


class SystemEventRepository(_BaseRepository):
    """CRUD and query operations for :class:`SystemEvent` records."""

    def create(
        self,
        event_type: str,
        message: str,
        severity: str = "info",
        source: Optional[str] = None,
        context: Optional[object] = None,
        timestamp: Optional[datetime] = None,
    ) -> SystemEvent:
        """Record a new system event.

        Args:
            event_type: Short machine-readable event category.
            message: Human readable description.
            severity: One of ``"info"``, ``"warning"``, ``"error"``.
            source: Originating module/component name.
            context: Optional structured JSON payload.
            timestamp: Event timestamp; defaults to database "now" if
                omitted.

        Returns:
            The newly created, flushed :class:`SystemEvent`.
        """
        event = SystemEvent(
            event_type=event_type,
            message=message,
            severity=severity,
            source=source,
            context=context,
        )
        if timestamp is not None:
            event.timestamp = timestamp
        self.session.add(event)
        self._flush()
        return event

    def get_by_id(self, event_id: int) -> Optional[SystemEvent]:
        """Fetch a system event by primary key.

        Args:
            event_id: The event's integer ID.

        Returns:
            The matching :class:`SystemEvent`, or ``None``.
        """
        return self.session.get(SystemEvent, event_id)

    def list_recent(
        self,
        limit: int = 100,
        event_type: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> List[SystemEvent]:
        """List the most recent system events, optionally filtered.

        Args:
            limit: Maximum number of events to return.
            event_type: Optional exact-match filter on event type.
            severity: Optional exact-match filter on severity.

        Returns:
            Up to ``limit`` :class:`SystemEvent` records, most recent
            first.
        """
        stmt = select(SystemEvent).order_by(SystemEvent.timestamp.desc()).limit(limit)
        if event_type is not None:
            stmt = stmt.where(SystemEvent.event_type == event_type)
        if severity is not None:
            stmt = stmt.where(SystemEvent.severity == severity)
        return list(self.session.execute(stmt).scalars().all())

    def list_in_range(
        self, start: datetime, end: datetime, page: int = 1, page_size: int = 100
    ) -> Page[SystemEvent]:
        """List events within a time range, paginated.

        Args:
            start: Inclusive start of the time range.
            end: Inclusive end of the time range.
            page: 1-indexed page number.
            page_size: Maximum records per page.

        Returns:
            A :class:`Page` of :class:`SystemEvent` records.
        """
        stmt = (
            select(SystemEvent)
            .where(SystemEvent.timestamp >= start, SystemEvent.timestamp <= end)
            .order_by(SystemEvent.timestamp.asc())
        )
        return _paginate(self.session, stmt, page, page_size)

    def delete(self, event_id: int) -> bool:
        """Delete a system event by ID.

        Args:
            event_id: The event's integer ID.

        Returns:
            ``True`` if an event was deleted, ``False`` if not found.
        """
        event = self.get_by_id(event_id)
        if event is None:
            return False
        self.session.delete(event)
        self._flush()
        return True


class ApplicationLogRepository(_BaseRepository):
    """CRUD and query operations for :class:`ApplicationLog` records."""

    def create(
        self,
        level: str,
        message: str,
        module: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> ApplicationLog:
        """Record a new application log entry.

        Args:
            level: Log level string (e.g. ``"INFO"``, ``"ERROR"``).
            message: The log message.
            module: Originating module/component name.
            timestamp: Log timestamp; defaults to database "now" if
                omitted.

        Returns:
            The newly created, flushed :class:`ApplicationLog`.
        """
        log_entry = ApplicationLog(level=level, message=message, module=module)
        if timestamp is not None:
            log_entry.timestamp = timestamp
        self.session.add(log_entry)
        self._flush()
        return log_entry

    def list_recent(self, limit: int = 100, level: Optional[str] = None) -> List[ApplicationLog]:
        """List the most recent application log entries.

        Args:
            limit: Maximum number of entries to return.
            level: Optional exact-match filter on log level.

        Returns:
            Up to ``limit`` :class:`ApplicationLog` records, most
            recent first.
        """
        stmt = select(ApplicationLog).order_by(ApplicationLog.timestamp.desc()).limit(limit)
        if level is not None:
            stmt = stmt.where(ApplicationLog.level == level)
        return list(self.session.execute(stmt).scalars().all())


def _paginate(session: Session, stmt, page: int, page_size: int) -> Page:
    """Execute a SELECT statement with offset/limit pagination.

    The total row count is computed with a SQL-level ``COUNT(*)``
    over the same filter predicate rather than materializing every
    matching row in Python, which matters once ``sensor_readings``
    grows into the tens of millions of rows expected after a few
    years of continuous 5-second sampling.

    Args:
        session: The active SQLAlchemy session.
        stmt: A SQLAlchemy ``Select`` statement (ordering already
            applied by the caller).
        page: 1-indexed page number (values below 1 are clamped to 1).
        page_size: Maximum records per page (values below 1 are
            clamped to 1).

    Returns:
        A :class:`Page` containing the requested slice of results
        plus the total matching row count.
    """
    page = max(1, page)
    page_size = max(1, page_size)

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = session.execute(count_stmt).scalar_one()

    paged_stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    items = list(session.execute(paged_stmt).scalars().all())

    return Page(items=items, total=total, page=page, page_size=page_size)
