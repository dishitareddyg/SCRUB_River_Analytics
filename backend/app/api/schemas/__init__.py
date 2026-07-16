"""Pydantic request/response schemas for the REST API layer.

One module per feature area, mirroring ``app/api/routers/``:

    - ``sensor.py``: live sensor reading schemas (``/live``).
    - ``analytics.py``: derived-parameter schemas (``/analytics``).
    - ``history.py``: historical sensor-reading schemas (``/history``).
    - ``system.py``: system health/info schemas (``/system``).

These schemas describe API *payloads* only - they are intentionally
separate from the ORM models in :mod:`app.database.models` and the
dataclasses in :mod:`app.analytics.result`/:mod:`app.serial.sensor_registry`,
so that internal representations can evolve without being a breaking
API change (and vice versa).
"""
