"""
conftest.py — Top-level pytest configuration for SCRUB v4.

Patches hardware-dependent imports so tests can run without physical hardware.
"""

import sys
import os
import types
from unittest.mock import MagicMock

NAV_SERVICE = os.path.join(os.path.dirname(__file__), "nav_service")
if NAV_SERVICE not in sys.path:
    sys.path.insert(0, NAV_SERVICE)


def _make_module(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


# --- serial ---
serial_mod = _make_module("serial")

class _FakeSerial:
    def __init__(self, *a, **kw):
        self.is_open = True
    def readline(self):
        return b""
    def write(self, data):
        pass
    def close(self):
        self.is_open = False

serial_mod.Serial = _FakeSerial

class _FakeSerialException(Exception):
    pass

serial_mod.SerialException = _FakeSerialException

# --- firebase_admin (optional) ---
try:
    import firebase_admin  # noqa: F401
except ImportError:
    fb_mod = _make_module("firebase_admin")
    fb_mod.initialize_app = MagicMock()
    fb_creds_mod = _make_module("firebase_admin.credentials")
    fb_creds_mod.Certificate = MagicMock()
    fb_db_mod = _make_module("firebase_admin.db")
    fb_db_mod.reference = MagicMock()

# --- uvicorn (optional for tests) ---
try:
    import uvicorn  # noqa: F401
except ImportError:
    uv_mod = _make_module("uvicorn")
    uv_mod.Config = MagicMock()
    uv_mod.Server = MagicMock()
