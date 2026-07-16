"""Feature-organized ``APIRouter`` modules.

Each module defines one ``router`` (an ``APIRouter`` instance) for a
single feature area, registered into the versioned ``api_router`` in
:mod:`app.api.routes`:

    - ``system.py``: ``/system/health``, ``/system/info``.
    - ``live.py``: ``/live/latest``.
    - ``analytics.py``: ``/analytics/latest``.
    - ``history.py``: ``/history/sensor/{sensor_name}``,
      ``/history/analytics/{parameter}``.

None of these routers perform analytics, run ML models, generate
reports, or write to the database - they only read through
:class:`app.database.service.DatabaseService` and
:class:`app.analytics.analytics_engine.AnalyticsEngine` and shape the
result into a response.
"""
