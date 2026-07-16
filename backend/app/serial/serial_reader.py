"""Low-level serial port reader.

Thin, defensive wrapper around ``pyserial`` responsible only for
opening/closing the port and reading one line at a time. It never
parses or validates packet content, and it never crashes the calling
thread on communication errors - failures are surfaced as
:class:`~app.utils.exceptions.CommunicationError` for the caller
(:mod:`app.serial.serial_manager`) to handle with its own
reconnect/backoff policy.
"""

from __future__ import annotations

from typing import List, Optional

import serial
from serial.tools import list_ports

from app.utils.exceptions import CommunicationError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SerialReader:
    """Reads newline-delimited text from an Arduino over USB serial."""

    def __init__(
        self,
        baud_rate: int,
        connect_timeout_seconds: float,
        read_timeout_seconds: float,
        max_line_bytes: int,
    ) -> None:
        """Initialize the reader.

        Args:
            baud_rate: Serial baud rate to use when opening the port.
            connect_timeout_seconds: Timeout applied while opening the
                port.
            read_timeout_seconds: Timeout applied to each blocking
                read call.
            max_line_bytes: Maximum number of bytes accepted for a
                single line before it is treated as corrupted and
                discarded.
        """
        self._baud_rate = baud_rate
        self._connect_timeout_seconds = connect_timeout_seconds
        self._read_timeout_seconds = read_timeout_seconds
        self._max_line_bytes = max_line_bytes
        self._connection: Optional[serial.Serial] = None

    @property
    def is_open(self) -> bool:
        """Whether the underlying serial connection is currently open.

        Returns:
            ``True`` if the port is open and ready to read.
        """
        return self._connection is not None and self._connection.is_open

    def open(self, port: str) -> None:
        """Open the given serial port.

        Args:
            port: OS-level port identifier (e.g. ``"COM3"`` or
                ``"/dev/ttyUSB0"``).

        Raises:
            CommunicationError: If the port cannot be opened.
        """
        try:
            self._connection = serial.Serial(
                port=port,
                baudrate=self._baud_rate,
                timeout=self._read_timeout_seconds,
                write_timeout=self._connect_timeout_seconds,
            )
            logger.info(f"Opened serial port '{port}' at {self._baud_rate} baud.")
        except (serial.SerialException, OSError) as exc:
            raise CommunicationError(f"Failed to open serial port '{port}': {exc}") from exc

    def close(self) -> None:
        """Close the serial connection, if open.

        Never raises - closing a failed/absent connection is a no-op.
        """
        if self._connection is not None:
            try:
                self._connection.close()
                logger.info("Serial connection closed.")
            except (serial.SerialException, OSError) as exc:  # pragma: no cover - defensive
                logger.warning(f"Error while closing serial connection: {exc}")
            finally:
                self._connection = None

    def read_line(self) -> Optional[str]:
        """Read a single newline-delimited line from the serial port.

        Returns:
            The decoded, stripped line, or ``None`` if the read timed
            out with no data (a normal, expected condition - not an
            error) or if the line was too long / undecodable and was
            discarded.

        Raises:
            CommunicationError: If the underlying serial connection is
                not open, or the read itself fails at the OS/driver
                level (e.g. the USB cable was disconnected).
        """
        if self._connection is None or not self._connection.is_open:
            raise CommunicationError("Attempted to read from a closed serial connection.")

        try:
            raw_bytes = self._connection.readline()
        except (serial.SerialException, OSError) as exc:
            raise CommunicationError(f"Serial read failed: {exc}") from exc

        if not raw_bytes:
            return None  # Read timeout with no data - normal, not an error.

        if len(raw_bytes) > self._max_line_bytes:
            logger.warning(
                f"Discarding oversized serial line ({len(raw_bytes)} bytes > "
                f"max {self._max_line_bytes})."
            )
            return None

        try:
            return raw_bytes.decode("utf-8", errors="strict").strip()
        except UnicodeDecodeError:
            logger.warning("Discarding serial line with invalid encoding.")
            return None

    @staticmethod
    def detect_port() -> Optional[str]:
        """Attempt to auto-detect a likely Arduino serial port.

        Scans available serial ports and returns the first one whose
        description or manufacturer string suggests an Arduino/USB
        serial device. This is a best-effort convenience only; a
        configured ``serial_com_port`` always takes precedence when
        auto-detection is disabled or fails.

        Returns:
            The detected port identifier, or ``None`` if no candidate
            port was found.
        """
        candidates: List[str] = []
        for port_info in list_ports.comports():
            description = f"{port_info.description or ''} {port_info.manufacturer or ''}".lower()
            if any(keyword in description for keyword in ("arduino", "usb", "ch340", "ftdi", "wch")):
                candidates.append(port_info.device)

        if not candidates:
            logger.warning("No candidate serial ports found during auto-detection.")
            return None

        logger.info(f"Auto-detected candidate serial port: {candidates[0]}")
        return candidates[0]
