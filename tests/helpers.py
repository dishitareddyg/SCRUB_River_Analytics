"""Shared test fixtures: settings overrides, fake serial port, mission payloads."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import tempfile
import threading
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings  # noqa: E402

GCS = (12.916860, 77.486980)


@contextlib.contextmanager
def override(**values):
    """Temporarily override fields of the frozen settings singleton."""
    old = {k: getattr(settings, k) for k in values}
    for k, v in values.items():
        object.__setattr__(settings, k, v)
    try:
        yield
    finally:
        for k, v in old.items():
            object.__setattr__(settings, k, v)


class FakeSerial:
    """Stand-in for serial.Serial: records writes, serves queued reads."""

    def __init__(self, chunks=None):
        self.is_open = True
        self.writes: list[bytes] = []
        self._chunks = list(chunks or [])
        self._lock = threading.Lock()

    def write(self, data: bytes) -> int:
        with self._lock:
            self.writes.append(bytes(data))
        return len(data)

    def flush(self):
        pass

    def read(self, _n):
        with self._lock:
            if self._chunks:
                item = self._chunks.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
        return b""

    def close(self):
        self.is_open = False

    def packets(self) -> list[dict]:
        with self._lock:
            return [json.loads(w) for w in self.writes]


def stm32_packet(lat=GCS[0], lon=GCS[1], heading=90.0, left=0, right=0, sensors=None, **extra):
    pkt = {
        "device_id": "BOT001",
        "timestamp": "2026-11-05T10:41:00.000Z",
        "motors": {"left": left, "right": right},
        "gps": {"latitude": lat, "longitude": lon},
        "compass": {"heading": heading},
        "sensors": sensors if sensors is not None else {
            "ph": 7.12, "tds": 214.2, "turbidity": 15.3,
            "temperature_c": 27.4, "humidity_percent": 71.2,
        },
    }
    pkt.update(extra)
    return pkt


def offset(lat, lon, north_m=0.0, east_m=0.0):
    import math
    return (lat + north_m / 110540.0,
            lon + east_m / (111320.0 * math.cos(math.radians(lat))))


def mission_payload(mission_id=None, rows=3, width_m=40.0, height_m=30.0):
    """Square polygon NE of the GCS with a simple boustrophedon route."""
    gcs = GCS
    p0 = offset(*gcs, 10, 10)
    p1 = offset(*gcs, 10, 10 + width_m)
    p2 = offset(*gcs, 10 + height_m, 10 + width_m)
    p3 = offset(*gcs, 10 + height_m, 10)
    polygon = [p0, p1, p2, p3]
    route = []
    for r in range(rows):
        north = 10 + 5 + r * ((height_m - 10) / max(1, rows - 1))
        a = offset(*gcs, north, 15)
        b = offset(*gcs, north, 5 + width_m)
        route.extend([a, b] if r % 2 == 0 else [b, a])
    pts = [("GCS", gcs)] + [("COVERAGE", p) for p in route] + [("GCS", gcs)]
    return {
        "mission_id": mission_id or str(uuid.uuid4()),
        "device_id": settings.DEVICE_ID,
        "ground_control": {"latitude": gcs[0], "longitude": gcs[1]},
        "polygon": [{"latitude": la, "longitude": lo} for la, lo in polygon],
        "waypoints": [
            {"sequence_order": i, "latitude": la, "longitude": lo, "type": t}
            for i, (t, (la, lo)) in enumerate(pts)
        ],
        "sweep_spacing_m": 5.0,
    }


class TempDir:
    def __enter__(self):
        self._td = tempfile.TemporaryDirectory()
        return self._td.name

    def __exit__(self, *exc):
        try:
            self._td.cleanup()
        except OSError:
            pass
