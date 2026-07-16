"""Device manager.

Tracks the identity and health counters of the connected Arduino
device: connection state, device ID, firmware version, last packet
time, packet counts, reconnect counts, and communication error
counts. Thread-safe, since it is updated from the serial acquisition
background thread and read from API/status code running on other
threads.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.serial.sensor_packet import SensorPacket


@dataclass(frozen=True)
class DeviceState:
    """Immutable snapshot of the tracked device's current state.

    Attributes:
        connected: Whether the serial connection is currently open.
        device_id: Identifier reported by the device, if known.
        firmware_version: Firmware version reported by the device, if
            known.
        last_packet_at: Timestamp the last valid packet was received.
        packet_count: Total number of packets successfully received
            and queued since the process started.
        reconnect_count: Total number of times the connection has been
            re-established since the process started.
        communication_errors: Total number of communication errors
            (read failures, malformed packets, etc.) observed.
    """

    connected: bool
    device_id: Optional[str]
    firmware_version: Optional[str]
    last_packet_at: Optional[datetime]
    packet_count: int
    reconnect_count: int
    communication_errors: int


class DeviceManager:
    """Thread-safe tracker of the connected Arduino device's state."""

    def __init__(self) -> None:
        """Initialize the manager with an empty/disconnected state."""
        self._lock = threading.Lock()
        self._connected = False
        self._device_id: Optional[str] = None
        self._firmware_version: Optional[str] = None
        self._last_packet_at: Optional[datetime] = None
        self._packet_count = 0
        self._reconnect_count = 0
        self._communication_errors = 0

    def mark_connected(self) -> None:
        """Record that the serial connection was successfully opened."""
        with self._lock:
            self._connected = True

    def mark_disconnected(self) -> None:
        """Record that the serial connection was closed or lost."""
        with self._lock:
            self._connected = False

    def record_reconnect(self) -> None:
        """Record a successful reconnect attempt."""
        with self._lock:
            self._reconnect_count += 1
            self._connected = True

    def record_error(self) -> None:
        """Record a communication error (read failure, bad packet, etc.)."""
        with self._lock:
            self._communication_errors += 1

    def record_packet(self, packet: SensorPacket) -> None:
        """Record receipt of a valid packet and refresh device metadata.

        Args:
            packet: The successfully validated packet. Its
                ``device_id`` (and, if present, a ``firmware_version``
                field on the raw payload) update the tracked device
                metadata.
        """
        with self._lock:
            self._packet_count += 1
            self._last_packet_at = packet.received_at
            if packet.device_id:
                self._device_id = packet.device_id
            firmware_version = packet.raw.get("firmware_version")
            if firmware_version:
                self._firmware_version = str(firmware_version)

    def snapshot(self) -> DeviceState:
        """Return an immutable snapshot of the current device state.

        Returns:
            A :class:`DeviceState` copy safe to read without holding
            the internal lock.
        """
        with self._lock:
            return DeviceState(
                connected=self._connected,
                device_id=self._device_id,
                firmware_version=self._firmware_version,
                last_packet_at=self._last_packet_at,
                packet_count=self._packet_count,
                reconnect_count=self._reconnect_count,
                communication_errors=self._communication_errors,
            )
