"""Unit tests for :mod:`app.serial.queue_manager`."""

from __future__ import annotations

from datetime import datetime, timezone

from app.serial.queue_manager import PacketQueue
from app.serial.sensor_packet import SensorPacket


def _make_packet(sequence: int) -> SensorPacket:
    """Build a minimal SensorPacket for queue testing.

    Args:
        sequence: Sequence number to tag the packet with, so ordering
            can be asserted on later.

    Returns:
        A :class:`SensorPacket` instance.
    """
    return SensorPacket(
        device_id="river-bot-01",
        sequence=sequence,
        timestamp_raw="2026-07-12T09:30:00Z",
        timestamp=datetime(2026, 7, 12, 9, 30, tzinfo=timezone.utc),
        sensors_raw={"do": 6.5},
        raw={},
    )


def test_put_and_get_preserves_fifo_order() -> None:
    """Packets should come out in the order they went in, under capacity."""
    q = PacketQueue(max_size=10)
    q.put(_make_packet(1))
    q.put(_make_packet(2))
    q.put(_make_packet(3))

    assert q.get().sequence == 1
    assert q.get().sequence == 2
    assert q.get().sequence == 3


def test_get_returns_none_on_timeout_when_empty() -> None:
    """Getting from an empty queue with a short timeout should return None."""
    q = PacketQueue(max_size=10)
    assert q.get(timeout=0.05) is None


def test_qsize_and_is_full_reflect_state() -> None:
    """qsize()/is_full() should accurately reflect the queue's fill level."""
    q = PacketQueue(max_size=2)
    assert q.qsize() == 0
    assert not q.is_full()

    q.put(_make_packet(1))
    q.put(_make_packet(2))

    assert q.qsize() == 2
    assert q.is_full()


def test_overflow_drops_oldest_packet_and_increments_counter() -> None:
    """Pushing past capacity should drop the oldest packet, not raise."""
    q = PacketQueue(max_size=2)
    q.put(_make_packet(1))
    q.put(_make_packet(2))
    q.put(_make_packet(3))  # Should drop sequence=1.

    assert q.dropped_count == 1
    remaining = [q.get().sequence, q.get().sequence]
    assert remaining == [2, 3]
