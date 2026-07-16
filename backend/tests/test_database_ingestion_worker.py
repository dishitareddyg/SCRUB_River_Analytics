"""Tests for :mod:`app.database.ingestion_worker`."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pytest

from app.database.ingestion_worker import IngestionWorker
from app.database.service import DatabaseService
from app.serial.packet_parser import PacketParser
from app.serial.packet_validator import PacketValidator
from app.serial.queue_manager import PacketQueue
from app.serial.sensor_packet import SensorPacket
from tests.database_test_helpers import build_test_session_factory, session_scope_factory_for
from tests.serial_test_helpers import build_test_registry


def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.02) -> bool:
    """Poll ``predicate`` until it returns True or the timeout elapses.

    Args:
        predicate: A zero-argument callable returning a boolean.
        timeout: Maximum time to wait, in seconds.
        interval: Poll interval, in seconds.

    Returns:
        ``True`` if the predicate became true within the timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture
def db_service(tmp_path) -> DatabaseService:
    """Provide a DatabaseService backed by a fresh in-memory SQLite database."""
    factory = build_test_session_factory()
    return DatabaseService(session_scope_factory=session_scope_factory_for(factory))


def _valid_packet(registry, sequence: int = 1) -> SensorPacket:
    """Build and validate a realistic packet for ingestion tests.

    Args:
        registry: The SensorRegistry to validate against.
        sequence: Packet sequence number.

    Returns:
        A validated :class:`SensorPacket`.
    """
    line = json.dumps(
        {
            "timestamp": "2026-07-12T09:30:00Z",
            "device_id": "river-bot-01",
            "sequence": sequence,
            "sensors": {"do": 6.5, "ph": 7.1},
        }
    )
    packet = PacketParser().parse(line)
    PacketValidator(registry).validate(packet)
    return packet


def test_ingestion_worker_persists_queued_packets(db_service: DatabaseService, tmp_path) -> None:
    """Packets pushed onto the queue should end up persisted in the database."""
    registry = build_test_registry(tmp_path)
    db_service.sync_sensor_registry(registry)

    queue = PacketQueue(max_size=50)
    worker = IngestionWorker(queue=queue, database_service=db_service, poll_timeout_seconds=0.05)
    worker.start()

    try:
        queue.put(_valid_packet(registry, sequence=1))
        queue.put(_valid_packet(registry, sequence=2))

        assert _wait_until(lambda: worker.stored_count >= 2)

        latest = db_service.get_latest_readings(
            device_name="river-bot-01", sensor_key="dissolved_oxygen", limit=5
        )
        assert len(latest) == 2
    finally:
        worker.stop()


def test_ingestion_worker_counts_errors_without_crashing(db_service: DatabaseService) -> None:
    """A packet that fails to persist (e.g. no device_id) should be counted,
    not crash the worker thread."""
    queue = PacketQueue(max_size=10)
    worker = IngestionWorker(queue=queue, database_service=db_service, poll_timeout_seconds=0.05)
    worker.start()

    try:
        bad_packet = SensorPacket(
            device_id=None,
            sequence=1,
            timestamp_raw=None,
            timestamp=None,
            sensors_raw={},
            raw={},
        )
        queue.put(bad_packet)

        assert _wait_until(lambda: worker.error_count >= 1)
        assert worker.stored_count == 0
    finally:
        worker.stop()


def test_ingestion_worker_stop_is_graceful_and_idempotent(db_service: DatabaseService) -> None:
    """stop() should cleanly halt the thread and be safe to call twice."""
    queue = PacketQueue(max_size=10)
    worker = IngestionWorker(queue=queue, database_service=db_service, poll_timeout_seconds=0.05)
    worker.start()
    worker.stop()
    worker.stop()  # Must not raise.
