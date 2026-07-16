"""Database package.

Provides:

    - ``db.py``               : SQLAlchemy engine + connection manager.
    - ``session.py``          : session factory, ``get_db`` FastAPI
                                  dependency, and ``session_scope`` for
                                  non-request (background thread) use.
    - ``base.py``              : shared declarative ORM base.
    - ``types.py``              : cross-dialect GUID column type.
    - ``models.py``             : ORM models (Device, Sensor,
                                  SensorReading, ApplicationLog,
                                  SystemEvent).
    - ``crud.py``               : repository classes (Repository
                                  pattern) with CRUD + pagination +
                                  time-range + latest-value queries.
    - ``retention.py``          : opt-in archive/purge helpers for
                                  ``sensor_readings`` (nothing runs
                                  automatically).
    - ``service.py``            : ``DatabaseService`` facade - the
                                  single entry point future modules
                                  should use to read/write data.
    - ``ingestion_worker.py``   : background thread bridging the
                                  serial module's packet queue into
                                  ``DatabaseService`` without modifying
                                  ``app/serial``.

No sensor-specific hardware models are referenced anywhere in this
package; sensor identity/units/ranges are entirely data-driven via the
``sensors`` table (itself synced from ``app/config/sensors.yaml``).
"""
