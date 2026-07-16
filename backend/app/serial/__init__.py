"""Serial communication / data acquisition package.

Implements reliable acquisition of sensor telemetry from the Arduino
Uno over USB serial:

    - ``serial_reader.py``    : low-level pyserial line reader.
    - ``packet_parser.py``    : raw line -> structured SensorPacket.
    - ``packet_validator.py`` : domain validation of SensorPacket.
    - ``sensor_packet.py``    : SensorPacket / SensorReading models.
    - ``sensor_registry.py``  : loads and indexes app/config/sensors.yaml.
    - ``queue_manager.py``    : thread-safe in-memory packet queue.
    - ``device_manager.py``   : tracks connected-device state/counters.
    - ``status.py``           : tracks connection status/frequency/latency.
    - ``serial_manager.py``   : background-thread orchestrator tying the
                                 above together, with automatic reconnect.

This package is responsible ONLY for reliable data acquisition. It
does not write to the database, compute analytics, run machine
learning, or generate reports - those remain the responsibility of
future modules, which consume validated packets from
``SerialManager.queue``.
"""

from app.serial.device_manager import DeviceManager, DeviceState
from app.serial.packet_parser import PacketParser
from app.serial.packet_validator import PacketValidator, ValidationResult
from app.serial.queue_manager import PacketQueue
from app.serial.sensor_packet import SensorPacket, SensorReading
from app.serial.sensor_registry import SensorDefinition, SensorRegistry, get_sensor_registry
from app.serial.serial_manager import SerialManager
from app.serial.serial_reader import SerialReader
from app.serial.status import AcquisitionStatus, ConnectionStatus, StatusManager

__all__ = [
    "DeviceManager",
    "DeviceState",
    "PacketParser",
    "PacketValidator",
    "ValidationResult",
    "PacketQueue",
    "SensorPacket",
    "SensorReading",
    "SensorDefinition",
    "SensorRegistry",
    "get_sensor_registry",
    "SerialManager",
    "SerialReader",
    "AcquisitionStatus",
    "ConnectionStatus",
    "StatusManager",
]
