"""Integration tests for :mod:`app.serial.serial_manager`.

These tests never touch a real serial port. Instead, they monkeypatch
``serial.Serial`` (as imported inside
:mod:`app.serial.serial_reader`) with an in-memory fake that can be
configured to: yield a scripted sequence of lines, raise on open to
simulate an unavailable port, or raise mid-stream to simulate a
removed USB cable / Arduino reset - exercising the manager's
reconnect logic end-to-end.
"""

from __future__ import annotations

import json
import time
from typing import List, Optional

import pytest
import serial as pyserial

from app.config.settings import Settings
from app.serial.serial_manager import SerialManager
from app.serial.status import ConnectionStatus
from tests.serial_test_helpers import build_test_registry


def _valid_line(sequence: int) -> str:
    """Build a valid JSON packet line for the given sequence number.

    Args:
        sequence: Sequence number to embed in the packet.

    Returns:
        A JSON-encoded packet string.
    """
    return json.dumps(
        {
            "timestamp": "2026-07-12T09:30:00Z",
            "device_id": "river-bot-01",
            "sequence": sequence,
            "sensors": {"do": 6.5, "ph": 7.1},
        }
    )


class FakeSerial:
    """In-memory stand-in for ``serial.Serial`` used by these tests.

    Configured via class-level attributes reset before each test so
    every test gets deterministic, isolated behavior.
    """

    fail_open_times: int = 0
    lines_to_yield: List[str] = []
    raise_after_reads: Optional[int] = None
    open_calls: int = 0

    def __init__(self, port: str, baudrate: int, timeout: float, write_timeout: float) -> None:
        FakeSerial.open_calls += 1
        if FakeSerial.open_calls <= FakeSerial.fail_open_times:
            raise pyserial.SerialException("mock: port unavailable")

        self.is_open = True
        self._lines = list(FakeSerial.lines_to_yield)
        self._read_count = 0

    def readline(self) -> bytes:
        self._read_count += 1
        if (
            FakeSerial.raise_after_reads is not None
            and self._read_count > FakeSerial.raise_after_reads
        ):
            raise pyserial.SerialException("mock: cable removed")

        if self._lines:
            line = self._lines.pop(0)
            return (line + "\n").encode("utf-8")

        time.sleep(0.01)  # Simulate a read timeout with no data available.
        return b""

    def close(self) -> None:
        self.is_open = False


@pytest.fixture(autouse=True)
def _reset_fake_serial():
    """Reset FakeSerial class state before every test in this module."""
    FakeSerial.fail_open_times = 0
    FakeSerial.lines_to_yield = []
    FakeSerial.raise_after_reads = None
    FakeSerial.open_calls = 0
    yield


@pytest.fixture
def patched_serial(monkeypatch: pytest.MonkeyPatch):
    """Patch the ``serial.Serial`` class used by SerialReader with FakeSerial."""
    monkeypatch.setattr("app.serial.serial_reader.serial.Serial", FakeSerial)
    return FakeSerial


def _test_settings(**overrides: object) -> Settings:
    """Build Settings tuned for fast, deterministic serial tests.

    Args:
        **overrides: Additional settings fields to override.

    Returns:
        A :class:`Settings` instance.
    """
    defaults = dict(
        serial_com_port="COM_TEST",
        serial_auto_detect=False,
        serial_baud_rate=9600,
        serial_connect_timeout_seconds=0.1,
        serial_read_timeout_seconds=0.05,
        serial_reconnect_delay_seconds=0.05,
        serial_max_reconnect_delay_seconds=0.2,
        serial_max_line_bytes=4096,
        serial_queue_max_size=50,
    )
    defaults.update(overrides)
    return Settings(**defaults)  # type: ignore[arg-type]


def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.02) -> bool:
    """Poll ``predicate`` until it returns True or the timeout elapses.

    Args:
        predicate: A zero-argument callable returning a boolean.
        timeout: Maximum time to wait, in seconds.
        interval: Poll interval, in seconds.

    Returns:
        ``True`` if the predicate became true within the timeout,
        ``False`` otherwise.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_serial_manager_reads_valid_packets_into_queue(patched_serial, tmp_path) -> None:
    """Valid scripted lines should end up as queued, validated packets."""
    FakeSerial.lines_to_yield = [_valid_line(1), _valid_line(2), _valid_line(3)]

    manager = SerialManager(settings=_test_settings(), registry=build_test_registry(tmp_path))
    manager.start()
    try:
        assert _wait_until(lambda: manager.queue.qsize() >= 3)
        first = manager.queue.get(timeout=1.0)
        assert first is not None
        assert first.device_id == "river-bot-01"
        assert manager.devices.snapshot().packet_count >= 3
    finally:
        manager.stop()


def test_serial_manager_handles_malformed_lines_without_crashing(patched_serial, tmp_path) -> None:
    """Malformed lines interleaved with valid ones must not crash the thread,
    and only the valid packets should reach the queue."""
    FakeSerial.lines_to_yield = [
        "{not valid json",
        _valid_line(1),
        "also not json {{{",
        _valid_line(2),
    ]

    manager = SerialManager(settings=_test_settings(), registry=build_test_registry(tmp_path))
    manager.start()
    try:
        assert _wait_until(lambda: manager.queue.qsize() >= 2)
        sequences = set()
        while manager.queue.qsize():
            packet = manager.queue.get(timeout=0.5)
            if packet is not None:
                sequences.add(packet.sequence)
        assert sequences == {1, 2}
        assert manager.devices.snapshot().communication_errors >= 2
    finally:
        manager.stop()


def test_serial_manager_reconnects_after_open_failure(patched_serial, tmp_path) -> None:
    """The manager should retry opening the port after an initial failure."""
    FakeSerial.fail_open_times = 2  # First two open() calls fail, third succeeds.
    FakeSerial.lines_to_yield = [_valid_line(1)]

    manager = SerialManager(settings=_test_settings(), registry=build_test_registry(tmp_path))
    manager.start()
    try:
        assert _wait_until(lambda: FakeSerial.open_calls >= 3, timeout=3.0)
        assert _wait_until(lambda: manager.queue.qsize() >= 1, timeout=3.0)
        packet = manager.queue.get(timeout=1.0)
        assert packet is not None
        assert packet.sequence == 1
    finally:
        manager.stop()


def test_serial_manager_reconnects_after_cable_removed(patched_serial, tmp_path) -> None:
    """A mid-stream SerialException should trigger disconnect + reconnect,
    after which the device manager's reconnect_count should increase and
    the connection should recover."""
    FakeSerial.lines_to_yield = [_valid_line(1), _valid_line(2)]
    FakeSerial.raise_after_reads = 1  # Cable "removed" after the first read.

    manager = SerialManager(settings=_test_settings(), registry=build_test_registry(tmp_path))
    manager.start()
    try:
        assert _wait_until(lambda: manager.devices.snapshot().reconnect_count >= 1, timeout=3.0)
        assert _wait_until(lambda: FakeSerial.open_calls >= 2, timeout=3.0)
    finally:
        manager.stop()


def test_serial_manager_stop_is_graceful_and_idempotent(patched_serial, tmp_path) -> None:
    """stop() should cleanly halt the thread and be safe to call once more."""
    FakeSerial.lines_to_yield = [_valid_line(1)]

    manager = SerialManager(settings=_test_settings(), registry=build_test_registry(tmp_path))
    manager.start()
    assert _wait_until(lambda: manager.queue.qsize() >= 1)
    manager.stop()

    assert manager.devices.snapshot().connected is False
    assert manager.status.snapshot().status == ConnectionStatus.DISCONNECTED

    # Calling stop() again must not raise.
    manager.stop()


def test_serial_manager_no_port_available_reports_error_status(monkeypatch, tmp_path) -> None:
    """If auto-detection finds no candidate port, status should reflect ERROR
    rather than the thread crashing."""
    monkeypatch.setattr(
        "app.serial.serial_reader.SerialReader.detect_port", staticmethod(lambda: None)
    )

    settings = _test_settings(serial_com_port="auto", serial_auto_detect=True)
    manager = SerialManager(settings=settings, registry=build_test_registry(tmp_path))
    manager.start()
    try:
        assert _wait_until(lambda: manager.status.snapshot().status == ConnectionStatus.ERROR)
    finally:
        manager.stop()
