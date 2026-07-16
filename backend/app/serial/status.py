"""Status manager.

Tracks the live acquisition status exposed to the rest of the
backend: connection status, last packet timestamp, packet frequency,
packets-per-minute, and communication latency. This is purely an
observability component - it does not make decisions about
reconnecting or validating data.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Deque, Optional

_FREQUENCY_WINDOW_SECONDS = 60.0


class ConnectionStatus(str, Enum):
    """Possible states of the serial acquisition subsystem."""

    DISCONNECTED = "disconnected"
    WAITING = "waiting"
    CONNECTED = "connected"
    RECEIVING = "receiving"
    ERROR = "error"


@dataclass(frozen=True)
class AcquisitionStatus:
    """Immutable snapshot of the current acquisition status.

    Attributes:
        status: Current high-level :class:`ConnectionStatus`.
        last_packet_at: Timestamp of the most recently received valid
            packet, if any.
        packets_per_minute: Number of valid packets received in the
            trailing 60-second window.
        average_interval_seconds: Average time, in seconds, between
            the most recent packets in the tracked window, or ``None``
            if there is not enough data yet.
        last_latency_seconds: Time, in seconds, between the device's
            own reported timestamp and local receipt time for the
            most recent packet, or ``None`` if unavailable.
    """

    status: ConnectionStatus
    last_packet_at: Optional[datetime]
    packets_per_minute: int
    average_interval_seconds: Optional[float]
    last_latency_seconds: Optional[float]


class StatusManager:
    """Thread-safe tracker of live serial acquisition status."""

    def __init__(self) -> None:
        """Initialize the manager in a disconnected/waiting state."""
        self._lock = threading.Lock()
        self._status = ConnectionStatus.DISCONNECTED
        self._last_packet_at: Optional[datetime] = None
        self._last_latency_seconds: Optional[float] = None
        self._recent_packet_times: Deque[datetime] = deque(maxlen=600)

    def set_status(self, status: ConnectionStatus) -> None:
        """Explicitly set the high-level connection status.

        Args:
            status: The new :class:`ConnectionStatus`.
        """
        with self._lock:
            self._status = status

    def record_packet_received(self, packet_timestamp: Optional[datetime]) -> None:
        """Record that a valid packet was just received.

        Updates the status to :attr:`ConnectionStatus.RECEIVING`,
        refreshes the last-packet timestamp, appends to the rolling
        frequency window, and computes latency relative to the
        device-reported timestamp when available.

        Args:
            packet_timestamp: The device-reported timestamp on the
                packet, if it was parseable.
        """
        now = datetime.now(timezone.utc)
        with self._lock:
            self._status = ConnectionStatus.RECEIVING
            self._last_packet_at = now
            self._recent_packet_times.append(now)

            if packet_timestamp is not None:
                reference = packet_timestamp
                if reference.tzinfo is None:
                    reference = reference.replace(tzinfo=timezone.utc)
                self._last_latency_seconds = (now - reference).total_seconds()
            else:
                self._last_latency_seconds = None

    def snapshot(self) -> AcquisitionStatus:
        """Return an immutable snapshot of the current acquisition status.

        Returns:
            An :class:`AcquisitionStatus` computed from the current
            internal state.
        """
        with self._lock:
            now = datetime.now(timezone.utc)
            window_start = now.timestamp() - _FREQUENCY_WINDOW_SECONDS
            recent = [t for t in self._recent_packet_times if t.timestamp() >= window_start]

            average_interval: Optional[float] = None
            if len(recent) >= 2:
                span = (recent[-1] - recent[0]).total_seconds()
                average_interval = span / (len(recent) - 1) if span > 0 else 0.0

            return AcquisitionStatus(
                status=self._status,
                last_packet_at=self._last_packet_at,
                packets_per_minute=len(recent),
                average_interval_seconds=average_interval,
                last_latency_seconds=self._last_latency_seconds,
            )
