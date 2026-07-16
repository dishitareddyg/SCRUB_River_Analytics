"""Unit tests for :mod:`app.serial.device_manager` and :mod:`app.serial.status`."""

from __future__ import annotations

from datetime import datetime, timezone

from app.serial.device_manager import DeviceManager
from app.serial.sensor_packet import SensorPacket
from app.serial.status import ConnectionStatus, StatusManager


def _make_packet(device_id: str = "river-bot-01", firmware_version: str | None = None) -> SensorPacket:
    """Build a minimal SensorPacket for device/status manager tests.

    Args:
        device_id: Device identifier to tag the packet with.
        firmware_version: Optional firmware version to embed in the
            packet's raw payload.

    Returns:
        A :class:`SensorPacket` instance.
    """
    raw = {}
    if firmware_version is not None:
        raw["firmware_version"] = firmware_version
    return SensorPacket(
        device_id=device_id,
        sequence=1,
        timestamp_raw="2026-07-12T09:30:00Z",
        timestamp=datetime(2026, 7, 12, 9, 30, tzinfo=timezone.utc),
        sensors_raw={"do": 6.5},
        raw=raw,
    )


def test_device_manager_starts_disconnected() -> None:
    """A fresh DeviceManager should report a disconnected, empty state."""
    manager = DeviceManager()
    state = manager.snapshot()

    assert state.connected is False
    assert state.device_id is None
    assert state.packet_count == 0
    assert state.reconnect_count == 0
    assert state.communication_errors == 0


def test_device_manager_tracks_connection_lifecycle() -> None:
    """mark_connected/mark_disconnected/record_reconnect should update state."""
    manager = DeviceManager()

    manager.mark_connected()
    assert manager.snapshot().connected is True

    manager.mark_disconnected()
    assert manager.snapshot().connected is False

    manager.record_reconnect()
    state = manager.snapshot()
    assert state.connected is True
    assert state.reconnect_count == 1


def test_device_manager_records_packet_metadata() -> None:
    """record_packet should update device_id, firmware_version, and counters."""
    manager = DeviceManager()
    manager.record_packet(_make_packet(firmware_version="1.4.0"))

    state = manager.snapshot()
    assert state.packet_count == 1
    assert state.device_id == "river-bot-01"
    assert state.firmware_version == "1.4.0"
    assert state.last_packet_at is not None


def test_device_manager_records_errors() -> None:
    """record_error should increment the communication_errors counter."""
    manager = DeviceManager()
    manager.record_error()
    manager.record_error()

    assert manager.snapshot().communication_errors == 2


def test_status_manager_starts_disconnected() -> None:
    """A fresh StatusManager should report DISCONNECTED with no packet history."""
    manager = StatusManager()
    status = manager.snapshot()

    assert status.status == ConnectionStatus.DISCONNECTED
    assert status.last_packet_at is None
    assert status.packets_per_minute == 0


def test_status_manager_set_status() -> None:
    """set_status should be reflected in the next snapshot."""
    manager = StatusManager()
    manager.set_status(ConnectionStatus.WAITING)
    assert manager.snapshot().status == ConnectionStatus.WAITING


def test_status_manager_record_packet_updates_status_and_frequency() -> None:
    """record_packet_received should move to RECEIVING and count the packet."""
    manager = StatusManager()
    manager.record_packet_received(datetime.now(timezone.utc))

    status = manager.snapshot()
    assert status.status == ConnectionStatus.RECEIVING
    assert status.last_packet_at is not None
    assert status.packets_per_minute == 1


def test_status_manager_computes_latency_from_device_timestamp() -> None:
    """Latency should reflect the gap between device timestamp and receipt."""
    manager = StatusManager()
    past_timestamp = datetime.now(timezone.utc)
    manager.record_packet_received(past_timestamp)

    status = manager.snapshot()
    assert status.last_latency_seconds is not None
    assert status.last_latency_seconds >= 0
