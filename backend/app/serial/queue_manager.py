"""In-memory, thread-safe packet queue.

Validated packets are pushed onto this queue by the serial
acquisition subsystem. Future modules (database persistence,
analytics, machine learning) will consume packets from here. No
consumer logic is implemented in this module - it only provides a
safe, bounded hand-off point between the acquisition thread and
downstream modules.
"""

from __future__ import annotations

import queue
from typing import Optional

from app.serial.sensor_packet import SensorPacket
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PacketQueue:
    """A bounded, thread-safe FIFO queue of validated sensor packets.

    Built on the standard library's :class:`queue.Queue`, which is
    already thread-safe, so this class mainly adds domain-specific
    naming, an overflow policy, and logging.
    """

    def __init__(self, max_size: int) -> None:
        """Initialize the queue.

        Args:
            max_size: Maximum number of packets buffered before the
                oldest packet is dropped to make room for new ones.
        """
        self._max_size = max_size
        self._queue: "queue.Queue[SensorPacket]" = queue.Queue(maxsize=max_size)
        self._dropped_count = 0

    def put(self, packet: SensorPacket) -> None:
        """Push a validated packet onto the queue.

        If the queue is full, the oldest queued packet is discarded
        to make room, favoring the most recent (freshest) telemetry
        over strict FIFO durability - appropriate for a live
        monitoring system where downstream modules care most about
        current readings.

        Args:
            packet: The validated packet to enqueue.
        """
        try:
            self._queue.put_nowait(packet)
        except queue.Full:
            try:
                discarded = self._queue.get_nowait()
                self._dropped_count += 1
                logger.warning(
                    f"Packet queue full (max_size={self._max_size}); "
                    f"dropped oldest packet (device={discarded.device_id}, "
                    f"sequence={discarded.sequence})."
                )
            except queue.Empty:  # pragma: no cover - race condition guard
                pass
            self._queue.put_nowait(packet)

    def get(self, timeout: Optional[float] = None) -> Optional[SensorPacket]:
        """Pop the oldest packet from the queue, blocking up to ``timeout``.

        Args:
            timeout: Maximum time, in seconds, to wait for a packet.
                ``None`` waits indefinitely.

        Returns:
            The next :class:`SensorPacket`, or ``None`` if the timeout
            elapsed with no packet available.
        """
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def qsize(self) -> int:
        """Return the current (approximate) number of queued packets.

        Returns:
            The number of packets currently buffered.
        """
        return self._queue.qsize()

    def is_full(self) -> bool:
        """Return whether the queue is currently at capacity.

        Returns:
            ``True`` if the queue is full.
        """
        return self._queue.full()

    @property
    def dropped_count(self) -> int:
        """Total number of packets dropped due to a full queue.

        Returns:
            The cumulative count of dropped packets since this queue
            was created.
        """
        return self._dropped_count
