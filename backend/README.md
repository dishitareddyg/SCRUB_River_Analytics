# River Intelligence Platform — Backend (Modules 1-6)

## Project Overview

The **River Intelligence Platform (RIP)** is a local, hardware-connected
system for monitoring river water quality using an Arduino Uno wired
to a computer over USB serial. The full system will eventually stream
sensor readings into a PostgreSQL/TimescaleDB database, run analytics
and machine learning on the collected data, and expose everything to
a React dashboard through a FastAPI backend.

**Module 1 (Backend Foundation)** establishes a stable, modular
architecture — configuration, logging, database plumbing, error
handling, response contracts, and the FastAPI application shell — that
every future module plugs into **without requiring the architecture to
change.**

**Module 2 (Serial Communication / Data Acquisition)** is a robust,
thread-safe subsystem (`app/serial/`) that reads JSON telemetry
packets from the Arduino Uno over USB serial, validates them against
configurable sensor definitions, and makes validated packets available
via an in-memory queue.

**Module 3 (Database Layer)** — see
[Database Layer](#database-layer) below — persists validated packets,
device metadata, and sensor metadata into PostgreSQL/TimescaleDB via a
Repository-pattern CRUD layer and a `DatabaseService` facade, and
bridges Module 2's packet queue into storage without modifying
`app/serial` at all.

**Module 4 (Analytics Engine)** — see
[Analytics Engine](#analytics-engine) below — is the mathematical
core of the platform: `app/analytics/` computes derived river
parameters (TDS, salinity, oxygen saturation/deficit, water density,
channel geometry, flow velocity, discharge, sediment load) from
validated sensor data retrieved through `DatabaseService`, using a
registry of swappable, individually-referenced calculators. It never
talks to the Arduino/serial layer directly and never persists its
own results.

**Module 5 (REST API)** — see [REST API](#rest-api) below — exposes
Modules 2-4's data through a versioned, read-only FastAPI surface
(`app/api/`): live sensor readings, the latest derived analytics, and
paginated history for both, organized into feature routers
(`system`, `live`, `analytics`, `history`) behind consistent
request/response schemas and error handling. It performs no
analytics of its own — every derived value comes from the Analytics
Engine — and writes nothing to the database.

**Module 6 (Historical Analytics & Trend Engine)** — see
[Historical Analytics & Trend Engine](#historical-analytics--trend-engine)
below — is a lightweight, pure-statistics layer (`app/historical/`)
that reads *already stored* sensor readings and derived analytics
through `DatabaseService` / the Analytics Engine and computes
statistical summaries, trend classifications, seasonal groupings,
bucketed aggregation, and two-parameter comparisons over configurable
time windows (last hour through last year, or a custom range). It
uses ordinary least-squares linear regression for trend
direction/confidence — explicitly **no Machine Learning, forecasting,
or prediction** — and exposes its results both as new REST endpoints
(`GET /history/statistics|trends|seasonal/{parameter}`,
`GET /history/compare`) and as a reusable `HistoricalAnalyticsService`
that a future ML/forecasting module can depend on directly.

Explicitly out of scope for this stage: Water Quality Index, River
Health Score, flood/pollution/thermal-stress/habitat/algal-bloom risk
scoring, machine learning, prediction, reports, WebSockets,
authentication, and alerts. Their package locations exist (`app/ml`)
but contain no business logic yet.

```
Arduino Uno
    │  USB Serial
    ▼
Serial Communication Module (app/serial)
    │  validated SensorPacket
    ▼
Database Layer (app/database)
    │
    ▼
PostgreSQL / TimescaleDB
    │
    ▼
Analytics Engine (app/analytics)
    │  CalculationResult
    ▼
REST API (app/api)
    │  JSON over HTTP
    ├──────────────────────────────┐
    ▼                              ▼
React Dashboard (frontend/)   Historical Analytics & Trend
    │  Live/Analytics/Trends       Engine (app/historical) ◄── you are here
    │  pages consume REST API      │  statistics/trends/seasonal/
    ▼                              │  comparison, reusable by ↓
Future Modules                     ▼
                              Future ML / Prediction / Reports
```

## Architecture

- **Configuration (`app/config`)** — A single Pydantic `Settings`
  object (`get_settings()`) is the only source of environment-derived
  configuration in the codebase. `sensors.yaml` describes sensors
  generically (name, unit, range, sampling interval) with zero
  hardcoded hardware models.
- **Database (`app/database`)** — See
  [Database Layer](#database-layer) below. Fully implemented: ORM
  models, a Repository-pattern CRUD layer, a `DatabaseService` facade,
  retention helpers, and an `IngestionWorker` that bridges Module 2's
  packet queue into storage.
- **API (`app/api`)** — See [REST API](#rest-api) below. Fully
  implemented: feature routers (`system`, `live`, `analytics`,
  `history`) mounted into the single versioned `api_router` (at
  `API_V1_PREFIX`), Pydantic request/response schemas, a
  dependency-injection layer, and consistent error handling built on
  Module 1's existing response envelopes.
- **Utils (`app/utils`)** — Loguru-based logging with console +
  rotating daily file sinks (`logger.py`), a custom exception
  hierarchy (`exceptions.py`), and standardized
  Success/Error/Health response envelopes (`response.py`).
- **`app/main.py`** — The application factory: builds the `FastAPI`
  instance, attaches CORS + request-logging middleware, registers
  global exception handlers, mounts the versioned router, and manages
  startup/shutdown via a `lifespan` context manager.
- **Serial acquisition (`app/serial`)** — See
  [Serial Acquisition Subsystem](#serial-acquisition-subsystem) below.
  Fully implemented: reads Arduino telemetry, validates it against
  `sensors.yaml`, and queues it for the database layer to consume.
- **Analytics Engine (`app/analytics`)** — See
  [Analytics Engine](#analytics-engine) below. Fully implemented: a
  `BaseCalculator` interface, a self-registering calculator registry,
  thirteen derived-parameter calculators backed by published
  equations, and an `AnalyticsEngine` facade that resolves inputs
  through `DatabaseService`.
- **Historical Analytics & Trend Engine (`app/historical`)** — See
  [Historical Analytics & Trend Engine](#historical-analytics--trend-engine)
  below. Fully implemented: pure-statistics summary/trend/seasonal/
  aggregation/comparison functions, a shared time-window-resolution +
  data-fetching layer, and a `HistoricalAnalyticsService` facade
  consumed by new `app/api/routers/historical.py` endpoints.
- **ML (`app/ml`)** — Empty (docstring-only) package reserving its
  place in the architecture for a future module, so files never need
  to move between folders later.

## Folder Structure

```
backend/
├── app/
│   ├── config/
│   │   ├── settings.py       # Centralized Pydantic Settings
│   │   ├── constants.py      # Static, non-environment constants
│   │   ├── sensors.yaml      # Generic sensor definitions
│   │   └── analytics.yaml    # Analytics Engine equations/coefficients
│   ├── serial/                # Serial acquisition subsystem (Module 2)
│   │   ├── sensor_registry.py  # Loads/indexes sensors.yaml
│   │   ├── sensor_packet.py    # SensorPacket / SensorReading models
│   │   ├── serial_reader.py    # Low-level pyserial line reader
│   │   ├── packet_parser.py    # Raw line -> SensorPacket
│   │   ├── packet_validator.py # Domain validation of SensorPacket
│   │   ├── queue_manager.py    # Thread-safe in-memory packet queue
│   │   ├── device_manager.py   # Tracks connected-device state
│   │   ├── status.py           # Tracks connection status/frequency
│   │   └── serial_manager.py   # Background-thread orchestrator
│   ├── analytics/              # Analytics Engine (Module 4)
│   │   ├── result.py           # CalculationResult / CalculationStatus
│   │   ├── base.py             # BaseCalculator interface + CalculatorMetadata
│   │   ├── calculator_registry.py  # @register(key) / get_calculator(key)
│   │   ├── config.py           # Loads/types app/config/analytics.yaml
│   │   ├── equations.py        # Published formulas (no duplication)
│   │   ├── water_quality.py    # TDS, Salinity
│   │   ├── oxygen.py           # Oxygen Saturation, Oxygen Deficit
│   │   ├── density.py          # Water Density
│   │   ├── geometry.py         # River Width, Area, Perimeter, Radius, Depth
│   │   ├── hydrology.py        # Flow Velocity, River Discharge
│   │   ├── sediment.py         # Estimated Sediment Load
│   │   └── analytics_engine.py # AnalyticsEngine (DatabaseService integration)
│   ├── ml/                    # RESERVED — future ML module
│   ├── historical/              # Historical Analytics & Trend Engine (Module 6)
│   │   ├── statistics.py       # min/max/mean/median/std-dev/rolling stats
│   │   ├── trends.py           # OLS linear trend + direction classification
│   │   ├── aggregation.py      # hourly/daily/weekly/monthly bucketing
│   │   ├── seasonal.py         # hour/day/week/month/season/year grouping
│   │   ├── comparison.py       # two-parameter correlation/comparison
│   │   ├── utils.py            # time-window resolution + data fetching
│   │   ├── schemas.py          # Pydantic response models
│   │   └── service.py          # HistoricalAnalyticsService facade
│   ├── database/               # Database layer (Module 3)
│   │   ├── db.py               # Engine + connection manager
│   │   ├── session.py          # get_db (FastAPI) + session_scope (threads)
│   │   ├── base.py             # Declarative ORM base
│   │   ├── types.py            # Cross-dialect GUID column type
│   │   ├── models.py           # Device, Sensor, SensorReading, logs, events
│   │   ├── crud.py             # Repository pattern: CRUD + pagination + queries
│   │   ├── retention.py        # Opt-in archive/purge helpers (nothing automatic)
│   │   ├── service.py          # DatabaseService facade
│   │   └── ingestion_worker.py # Bridges app/serial's queue into storage
│   ├── api/                    # REST API layer (Module 5)
│   │   ├── routes.py          # Versioned router: mounts every feature router
│   │   ├── dependencies.py    # FastAPI Depends() providers (DI)
│   │   ├── responses.py       # Typed SuccessResponse[...] aliases + helpers
│   │   ├── routers/
│   │   │   ├── system.py      # GET /system/health, /system/info
│   │   │   ├── live.py        # GET /live/latest
│   │   │   ├── analytics.py   # GET /analytics/latest
│   │   │   ├── history.py     # GET /history/sensor/{name}, /history/analytics/{param}
│   │   │   └── historical.py  # GET /history/statistics|trends|seasonal/{param}, /history/compare
│   │   └── schemas/
│   │       ├── sensor.py      # Live-reading schemas
│   │       ├── analytics.py   # Derived-parameter schemas
│   │       ├── history.py     # History schemas + HistoryInterval
│   │       └── system.py      # Health/info schemas
│   ├── utils/
│   │   ├── logger.py         # Loguru configuration
│   │   ├── exceptions.py     # Custom exception hierarchy
│   │   └── response.py       # Success/Error/Health response models
│   └── main.py                # FastAPI application factory
├── alembic/                   # Migration environment (wired to app settings)
│   └── versions/
│       └── a78a2883a6ab_create_core_database_tables.py
├── tests/
│   ├── conftest.py
│   ├── test_health.py
│   ├── test_config.py
│   ├── analytics_test_helpers.py
│   ├── test_analytics_base.py
│   ├── test_analytics_registry.py
│   ├── test_analytics_equations.py
│   ├── test_analytics_water_quality.py
│   ├── test_analytics_oxygen.py
│   ├── test_analytics_density.py
│   ├── test_analytics_geometry.py
│   ├── test_analytics_hydrology.py
│   ├── test_analytics_sediment.py
│   ├── test_analytics_engine.py
│   ├── api_test_helpers.py
│   ├── test_api_system.py
│   ├── test_api_live.py
│   ├── test_api_analytics.py
│   ├── test_api_history.py
│   ├── historical_test_helpers.py
│   ├── test_historical_statistics.py
│   ├── test_historical_trends.py
│   ├── test_historical_aggregation.py
│   ├── test_historical_comparison.py
│   ├── test_historical_utils.py
│   ├── test_historical_service.py
│   └── test_api_historical.py
├── requirements.txt
├── pytest.ini
├── alembic.ini
├── .env.example
└── README.md
```

## Serial Acquisition Subsystem

### Architecture

```
SerialManager (background thread, owns the acquisition loop)
    │
    ├── SerialReader       — opens the COM port, reads one line at a time
    ├── PacketParser        — raw JSON line -> SensorPacket (structural only)
    ├── PacketValidator      — SensorPacket -> ValidationResult (domain rules)
    │       └── SensorRegistry — resolves/range-checks fields via sensors.yaml
    ├── PacketQueue          — bounded, thread-safe hand-off to future modules
    ├── DeviceManager        — connection/packet/error/reconnect counters
    └── StatusManager         — live status, packet frequency, latency
```

`SerialManager.start()` spawns a single daemon thread that never
blocks FastAPI. It resolves the COM port (configured or
auto-detected), opens it, and loops: read line → parse → validate →
push valid packets onto `PacketQueue` → update `DeviceManager` /
`StatusManager`. Any communication failure (bad open, read error,
cable pulled, Arduino reset) is caught, logged, and triggers a
reconnect using capped exponential backoff (`Event.wait`-based, never
a busy loop). `SerialManager.stop()` signals the thread via a
`threading.Event` and joins it for a graceful shutdown.

### Communication Flow

```
Arduino Uno --(JSON line, ~every 5s)--> SerialReader.read_line()
    -> PacketParser.parse() -> SensorPacket (or None if malformed JSON, dropped)
    -> PacketValidator.validate() -> ValidationResult
         (fatal errors -> packet dropped; per-field issues -> warnings only)
    -> PacketQueue.put() (valid packets only)
    -> DeviceManager.record_packet() / StatusManager.record_packet_received()
```

Future modules (Database & Storage, Analytics, ML) consume packets by
calling `serial_manager.queue.get(timeout=...)` — no consumer is
implemented in this module.

### Packet Format

One JSON object per line, e.g.:

```json
{
    "timestamp": "2026-07-12T09:30:00Z",
    "device_id": "river-bot-01",
    "sequence": 123,
    "sensors": {
        "do": 6.72,
        "ph": 7.24,
        "gps": { "latitude": 12.97, "longitude": 77.59 }
    }
}
```

- `sensors` field names are resolved against `sensors.yaml` by
  **canonical `sensor_name` or configured `aliases`** (e.g. `"do"` is
  an alias of `dissolved_oxygen`). Add new sensors or aliases purely
  by editing `sensors.yaml` — no Python changes required.
- Unrecognized `sensors` fields are preserved (not dropped) as an
  `is_known=False` reading and logged as a warning, so future firmware
  additions are visible even before `sensors.yaml` is updated.
- Unknown top-level fields (e.g. `firmware_version`, `battery`) are
  ignored for parsing purposes but retained in `SensorPacket.raw`.
- Malformed JSON, non-object payloads, and oversized lines are
  discarded with a logged warning — they never raise or crash the
  acquisition thread.

### Configuration

All settings below live in `app.config.settings.Settings` / `.env` —
nothing is hardcoded in `app/serial/`:

| Setting | Purpose |
|---|---|
| `SERIAL_COM_PORT` | Configured port, or `auto` to auto-detect |
| `SERIAL_AUTO_DETECT` | Enable/disable auto-detection fallback |
| `SERIAL_BAUD_RATE` | Serial baud rate |
| `SERIAL_CONNECT_TIMEOUT_SECONDS` | Timeout opening the port |
| `SERIAL_READ_TIMEOUT_SECONDS` | Timeout per blocking read |
| `SERIAL_RECONNECT_DELAY_SECONDS` | Base reconnect backoff delay |
| `SERIAL_MAX_RECONNECT_DELAY_SECONDS` | Backoff cap |
| `SERIAL_MAX_LINE_BYTES` | Discard lines longer than this |
| `SERIAL_QUEUE_MAX_SIZE` | Max buffered packets (oldest dropped when full) |
| `SAMPLING_INTERVAL_SECONDS` | Expected Arduino transmit interval |

Sensor identity, units, valid ranges, enabled/disabled state, and
aliases all live in `app/config/sensors.yaml`.

### Testing

```bash
pytest tests/test_serial_sensor_registry.py
pytest tests/test_serial_packet_parser.py
pytest tests/test_serial_packet_validator.py
pytest tests/test_serial_queue_manager.py
pytest tests/test_serial_device_status.py
pytest tests/test_serial_manager.py
```

`test_serial_manager.py` monkeypatches `serial.Serial` with an
in-memory fake (`FakeSerial`) to exercise the full acquisition loop
without real hardware, including: valid-packet queuing, malformed-line
resilience, reconnect-after-open-failure, and
reconnect-after-cable-removed scenarios.

## Database Layer

### Architecture

```
DatabaseService (facade — the only thing other modules should import)
    │
    ├── DeviceRepository        ┐
    ├── SensorRepository         │  Repository pattern, each wraps one
    ├── SensorReadingRepository  │  SQLAlchemy Session (CRUD + pagination
    ├── SystemEventRepository    │  + time-range + latest-value queries)
    ├── ApplicationLogRepository ┘
    │
    ▼
ORM models (Device, Sensor, SensorReading, ApplicationLog, SystemEvent)
    │
    ▼
PostgreSQL / TimescaleDB (sensor_readings is a hypertable on `timestamp`)
```

`IngestionWorker` (`app/database/ingestion_worker.py`) is a small
background thread — modeled on `SerialManager`'s own threading style
(daemon thread, `threading.Event`-based graceful stop, no busy-wait)
— that consumes packets from a `PacketQueue` (e.g.
`SerialManager.queue`) and calls
`DatabaseService.save_sensor_packet()` for each one. It requires zero
changes to `app/serial/`; it only reads from the queue Module 2
already writes into.

### Entity Relationships

```
devices (1) ───< sensor_readings >─── (1) sensors
   id                device_id, sensor_id           id
   device_name        timestamp (partition col)      sensor_key
   firmware_version    value / raw_value               display_name
   connection_status    validation_status               unit, ranges
   last_seen_at          packet_sequence                  enabled
```

- `sensor_readings.device_id` / `sensor_id` are foreign keys with
  `ON DELETE CASCADE` — deleting a device or sensor removes its
  historical readings.
- `sensor_readings` primary key is a **composite** `(id, timestamp)`,
  as required by TimescaleDB (every unique constraint on a hypertable
  must include the partitioning column).
- `application_logs` and `system_events` are standalone, lightweight
  monitoring tables with no foreign keys — intentionally simple.

No sensor-specific hardware models are referenced anywhere; a
`sensors` row is entirely data-driven (synced from
`app/config/sensors.yaml` via `DatabaseService.sync_sensor_registry()`
or registered ad hoc via `register_sensor()`).

### TimescaleDB Usage

The Alembic migration (`alembic/versions/..._create_core_database_tables.py`)
creates `sensor_readings` as a normal table via SQLAlchemy, then — only
when running against PostgreSQL — runs:

```sql
CREATE EXTENSION IF NOT EXISTS timescaledb;
SELECT create_hypertable('sensor_readings', 'timestamp', if_not_exists => TRUE, migrate_data => TRUE);
```

This partitions `sensor_readings` into per-time-range chunks
automatically, which keeps inserts and time-range queries fast even
after years of 5-second-interval, 15-20-sensor data (tens of millions
of rows). `raw_value`/`context` JSON columns use `JSONB` on
PostgreSQL. Indexes are created on `timestamp`, `(device_id,
timestamp)`, and `(sensor_id, timestamp)` so the common query
patterns (`get_latest_n`, `get_history`) never scan the full table.

Since this sandbox has no PostgreSQL/TimescaleDB instance available,
the migration was validated with `alembic upgrade head --sql`
(offline mode, prints the exact SQL Alembic would run without needing
a live connection) — see Testing (Database Layer) below for how the
ORM and repository logic itself is tested.

### Retention Strategy

Per this module's requirements, **raw sensor readings are retained
indefinitely by default** — nothing purges or aggregates data
automatically. `app/database/retention.py` (`RetentionManager`)
provides opt-in building blocks for a future scheduled job or admin
tool:

- `count_older_than(cutoff)` — preview how many rows a cutoff affects.
- `archive_to_csv(cutoff, output_path)` — stream-export rows with
  `timestamp < cutoff` to CSV, without deleting them.
- `purge_older_than(cutoff)` — permanently delete rows with
  `timestamp < cutoff` (bulk `DELETE`, not loaded into Python first).

No downsampling/aggregation is implemented (explicitly out of scope).

### Migration Workflow

```bash
# Apply all migrations (requires a running PostgreSQL/TimescaleDB, per .env)
alembic upgrade head

# Preview the SQL without a live database (useful for review/CI)
alembic upgrade head --sql

# After adding/changing models in app/database/models.py:
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

`alembic/env.py` imports `app.database.models` and reads
`DATABASE_URL` from `Settings`, so there is one source of truth for
both the connection string and the schema — no values are duplicated
in `alembic.ini`.

### Integration with Module 2

```python
from app.serial.serial_manager import SerialManager
from app.database.service import get_database_service
from app.database.ingestion_worker import IngestionWorker

serial_manager = SerialManager()
serial_manager.start()

ingestion_worker = IngestionWorker(
    queue=serial_manager.queue, database_service=get_database_service()
)
ingestion_worker.start()
```

`DatabaseService.save_sensor_packet()` resolves each reading's
canonical sensor name (already resolved by Module 2's
`PacketValidator` via `sensors.yaml` aliases), upserts the device,
inserts one `sensor_readings` row per resolvable reading, and logs a
`system_events` row (severity `warning`) for any reading whose sensor
isn't yet registered — without failing the rest of the packet. No
derived parameters are calculated and no analytics/ML are triggered,
per this module's scope. Wiring `IngestionWorker` into
`app/main.py`'s startup/shutdown lifecycle is left to a future
integration step.

### Testing (Database Layer)

```bash
pytest tests/test_database_models.py
pytest tests/test_database_crud.py
pytest tests/test_database_service.py
pytest tests/test_database_ingestion_worker.py
pytest tests/test_database_retention.py
```

Tests run against an in-memory SQLite database (`tests/database_test_helpers.py`)
rather than a live PostgreSQL/TimescaleDB instance, for speed and
isolation — made possible because `app/database/types.GUID` and the
JSON columns are cross-dialect. TimescaleDB-specific SQL
(`create_hypertable`) is validated separately via the `alembic upgrade
head --sql` offline dry run described above, since SQLite has no
TimescaleDB equivalent. `test_database_service.py` exercises the full
Module 2 → Module 3 path end-to-end, using Module 2's own
`PacketParser`/`PacketValidator` to build realistic packets before
handing them to `DatabaseService.save_sensor_packet()`.

## Analytics Engine

### Architecture

```
AnalyticsEngine (app/analytics/analytics_engine.py)
    │
    ├── DatabaseService.get_latest_readings()  — latest validated sensor values
    │       (never talks to app/serial directly)
    │
    ├── calculator_registry.get_calculator(key) / all_calculators()
    │       │
    │       └── BaseCalculator subclasses, one per derived parameter,
    │           each self-registered via @register(key):
    │             water_quality.py  → "tds", "salinity"
    │             oxygen.py         → "oxygen_saturation", "oxygen_deficit"
    │             density.py        → "water_density"
    │             geometry.py       → "river_width", "cross_sectional_area",
    │                                  "wetted_perimeter", "hydraulic_radius",
    │                                  "hydraulic_depth"
    │             hydrology.py      → "flow_velocity", "river_discharge"
    │             sediment.py       → "sediment_load"
    │
    └── config.py → AnalyticsConfig, loaded from app/config/analytics.yaml
            (every coefficient, equation choice, and correction factor —
             nothing is hardcoded in a calculator)
```

Every calculator implements the same `BaseCalculator` interface
(`metadata()`, `validate_inputs()`, `calculate()`) so equations can be
swapped or recalibrated without touching any calling code. Every
calculator's `metadata()` documents its formula name, scientific
reference, input/output units, required/optional inputs, assumptions,
limitations, and each input's valid operating range — all sourced
from a published engineering or scientific equation (see each
calculator module's docstrings and `app/analytics/equations.py` for
full citations: Hem 1985; Fofonoff & Millard 1983 / UNESCO PSS-78;
Benson & Krause 1984 / APHA 4500-O G; Kell 1975; Millero & Poisson
1981; Chow 1959; Manning 1891; Chezy 1775; Rasmussen et al. 2009;
Porterfield 1972; Asselman 2000).

### Calculation Contract

Every calculation — success or failure — returns a structured
`CalculationResult` (`app/analytics/result.py`):

```python
value               # the computed value, or None
status              # OK | NOT_COMPUTABLE | ERROR
unit                # e.g. "mg/L"
timestamp           # UTC, when the calculation ran
confidence          # 0.0-1.0, reflecting input/assumption quality
missing_inputs      # required inputs/config that were unavailable
formula_used        # human-readable formula name
reference           # scientific citation
warnings            # e.g. an input outside its documented valid range
inputs_used         # the raw inputs actually consumed, for traceability
error_message       # populated only when status is ERROR
```

A calculator never raises to its caller: missing sensor data or
unconfigured site geometry (e.g. an un-surveyed channel bed width)
always resolves to `NOT_COMPUTABLE` with `missing_inputs` populated —
values are never silently estimated. Every calculation stage (start,
completed, failed, missing inputs) is logged via
`app.utils.logger.get_logger`.

### Configuration (`app/config/analytics.yaml`)

Equation selection (e.g. Manning vs. Chezy for flow velocity, or the
sediment method), coefficients (e.g. the conductivity→TDS factor),
correction factors (e.g. the DO salinity/pressure corrections), and
site-survey geometry (channel bed width, side slope, longitudinal
slope) all live here — never hardcoded in Python. Site-survey values
are intentionally `null` by default; the affected calculators
(`river_width`, `cross_sectional_area`, `wetted_perimeter`,
`hydraulic_radius`, `hydraulic_depth`, `flow_velocity`,
`river_discharge`, `sediment_load`) report `NOT_COMPUTABLE` until a
deployment fills them in for its specific site.

### Usage

```python
from app.analytics.analytics_engine import AnalyticsEngine

engine = AnalyticsEngine()
result = engine.compute("tds")                       # one parameter
all_results = engine.compute_all(device_name="river-bot-01")  # every parameter
```

`AnalyticsEngine` resolves each calculator's declared inputs from
`DatabaseService.get_latest_readings()` (deduplicating shared inputs
across calculators in `compute_all()`), computes, and returns
`CalculationResult`s — it never stores them; persistence is left to a
later module.

### Explicitly Not Implemented

Per this module's scope: Water Quality Index, River Health Score,
Flood Risk, Pollution Risk, Thermal Stress, Habitat Suitability, Algal
Bloom Risk, machine learning, prediction, the dashboard, REST APIs,
and reports.

## REST API

All endpoints are mounted under the versioned prefix
`API_V1_PREFIX` (default `/api/v1`; see `app/config/settings.py`).
Interactive OpenAPI docs are available at `/docs` (Swagger UI) and
`/redoc` while the app is running, and the raw schema at
`/openapi.json`.

### Response Envelope

Every endpoint responds with Module 1's existing envelope models
(`app/utils/response.py`) — this module does not introduce a second
response shape:

```jsonc
// 2xx — SuccessResponse
{
  "success": true,
  "message": "Computed 13 derived parameter(s).",
  "data": { /* endpoint-specific payload */ },
  "meta": { "api_version": "v1", "timestamp": "2026-07-14T09:30:00Z" }
}
```

```jsonc
// 4xx/5xx — ErrorResponse
{
  "success": false,
  "message": "Request failed.",
  "error": {
    "type": "NotFoundError",
    "message": "Unknown sensor 'not_a_real_sensor'.",
    "context": {}
  },
  "meta": { "api_version": "v1", "timestamp": "2026-07-14T09:30:00Z" }
}
```

| Status | Meaning | Raised via |
| --- | --- | --- |
| `404` | Unknown sensor name or analytics parameter key | `app.utils.exceptions.NotFoundError` |
| `400` | Logically invalid request (e.g. conflicting query params, `start` after `end`) | `app.utils.exceptions.BadRequestError` |
| `422` | Malformed/mistyped query or path parameters (FastAPI/Pydantic request validation) | Global `RequestValidationError` handler (added to `app/main.py`) |
| `500` | Unhandled error | Existing global `Exception` handler |

### Endpoints

**System** (`app/api/routers/system.py`)

- `GET /system/health` — application status, database connectivity,
  serial acquisition connection status, app version, process uptime.
  Always returns `200`; clients inspect the individual status fields.
- `GET /system/info` — app name/version/environment, last known
  connected device + firmware version (from the serial acquisition
  subsystem's in-memory state), every configured sensor channel, and
  the configured database backend.

**Live** (`app/api/routers/live.py`)

- `GET /live/latest?device_name=` — the latest validated reading for
  every **enabled** sensor in `sensors.yaml`. Sensors that have never
  reported a value are included with `value: null` and
  `quality_status: "no_data"`, so the response shape is always
  complete. `quality_status` (`good` / `out_of_range` / `invalid` /
  `no_data`) is a coarse classification derived from the stored
  `validation_status` and the sensor's configured min/max range.

**Analytics** (`app/api/routers/analytics.py`)

- `GET /analytics/latest?device_name=` — every registered derived
  parameter (TDS, salinity, oxygen saturation/deficit, water density,
  channel geometry, flow velocity, river discharge, sediment load,
  ...), computed live via `AnalyticsEngine.compute_all()`. A
  parameter reports `status: "NOT_COMPUTABLE"` with its
  `missing_inputs` listed, rather than being omitted, when required
  sensor data or site configuration (e.g. an un-surveyed channel bed
  width) is unavailable.

**History** (`app/api/routers/history.py`)

- `GET /history/sensor/{sensor_name}?start=&end=&interval=&device_name=&page=&page_size=` —
  paginated historical readings for one sensor, oldest first. Supply
  either `interval` (`latest` / `hour` / `day` / `week` / `month`) or
  an explicit `start`/`end` range (both required together); defaults
  to the last day if neither is given. An unknown `sensor_name` is a
  `404`; conflicting/invalid range parameters are a `400`.
- `GET /history/analytics/{parameter}?start=&end=&interval=&device_name=&page=&page_size=` —
  a historical series for one derived parameter, recomputed via the
  real registered calculator (never reimplemented in the route). See
  the router module's docstring for the exact "anchor sensor + latest
  snapshot of other inputs" approximation it uses for ranged queries
  (the Analytics Engine only computes from *latest* readings and does
  not persist historical derived values); `interval=latest` instead
  delegates directly to `AnalyticsEngine.compute()` for an exact
  current value.

### Example Requests

```bash
curl http://localhost:8000/api/v1/live/latest
curl http://localhost:8000/api/v1/analytics/latest?device_name=river-bot-01
curl "http://localhost:8000/api/v1/history/sensor/dissolved_oxygen?interval=day"
curl "http://localhost:8000/api/v1/history/analytics/tds?interval=week&page=1&page_size=100"
curl "http://localhost:8000/api/v1/history/statistics/dissolved_oxygen?window=week"
curl "http://localhost:8000/api/v1/history/trends/tds?window=month"
curl "http://localhost:8000/api/v1/history/seasonal/dissolved_oxygen?group_by=season&window=year"
curl "http://localhost:8000/api/v1/history/compare?parameter_a=dissolved_oxygen&parameter_b=water_temperature&window=week"
```

### Example Response (`GET /analytics/latest`, abbreviated)

```jsonc
{
  "success": true,
  "message": "Computed 13 derived parameter(s).",
  "data": {
    "device_name": null,
    "results": [
      {
        "parameter": "tds",
        "display_name": "Total Dissolved Solids",
        "status": "OK",
        "value": 325.0,
        "unit": "mg/L",
        "timestamp": "2026-07-14T09:30:00Z",
        "confidence": 0.8,
        "formula_used": "Conductivity-to-TDS empirical conversion (Hem, 1985)",
        "reference": "Hem, J.D. (1985), USGS Water-Supply Paper 2254.",
        "missing_inputs": [],
        "warnings": [],
        "error_message": null
      },
      {
        "parameter": "river_width",
        "display_name": "River Width",
        "status": "NOT_COMPUTABLE",
        "value": null,
        "missing_inputs": ["geometry.bed_width_m (site survey configuration)"],
        "...": "..."
      }
    ]
  },
  "meta": { "api_version": "v1", "timestamp": "2026-07-14T09:30:00Z" }
}
```

### Dependency Injection

Every router obtains its collaborators via `Depends(...)` on the
providers in `app/api/dependencies.py`
(`get_database_service`, `get_analytics_engine_dependency`,
`get_sensor_registry_dependency`, `get_settings_dependency`,
`get_serial_manager_dependency`, `get_analytics_config_dependency`,
`get_historical_service_dependency`) — none of them import a
singleton directly. Tests override
`get_database_service` with an isolated in-memory SQLite
`DatabaseService` via `app.dependency_overrides` (see
`tests/api_test_helpers.py`), so the test suite never touches the
real configured database.

### Performance Notes

Tuned for the stated scale (~15 sensors, 5-second updates, a single
local user): `/live/latest` issues one small, indexed query per
enabled sensor (bounded, not unbounded); `/analytics/latest`
deduplicates shared sensor inputs across all 13 calculators into one
query per distinct input before computing. No caching layer is
introduced, since a single local user does not create meaningful
query pressure at this scale.

### Not Implemented (by design)

Per this module's scope: a dashboard, WebSockets, authentication/user
management, prediction, machine learning, reports, and alerts.

## Historical Analytics & Trend Engine

### Architecture

```
HistoricalAnalyticsService (app/historical/service.py)
    │  the only thing other modules (incl. the API layer) should import
    │
    ├── utils.resolve_time_window()      — "hour"/"day"/.../"year" shortcut
    │                                        or a custom start/end range
    ├── utils.fetch_parameter_series()   — resolves {parameter} to either:
    │       │                                a) a raw sensor  → paginates
    │       │                                   DatabaseService.get_sensor_history()
    │       │                                b) an analytics parameter →
    │       │                                   recomputes history via the
    │       │                                   same anchor-sensor approximation
    │       │                                   documented in
    │       │                                   app/api/routers/history.py
    │       ▼
    │   ParameterSeries — in-memory (timestamp, value) points, capped at
    │                      MAX_SERIES_POINTS (20,000) for very long ranges
    │
    ├── statistics.py   → min/max/avg/median/std-dev/variance/percent-change/
    │                      rolling mean/rolling std-dev/missing-value count
    ├── trends.py        → OLS linear_trend() → slope/intercept/r²,
    │                       classify_trend() → Increasing/Decreasing/Stable/
    │                       Rapid Increase/Rapid Decrease (no ML)
    ├── seasonal.py       → group by Hour/Day/Week/Month/Season/Year
    ├── aggregation.py     → Hourly/Daily/Weekly/Monthly buckets (read-only;
    │                        never modifies raw sensor_readings rows)
    └── comparison.py       → hourly-aligned Pearson correlation between
                              any two parameter series (e.g. DO vs
                              Temperature, Conductivity vs TDS)
```

Every dependency (`DatabaseService`, `SensorRegistry`,
`AnalyticsConfig`) is injected through `HistoricalAnalyticsService`'s
constructor rather than imported as a module-level singleton, matching
every other service in this codebase — tests build it against an
isolated in-memory `DatabaseService` (see `tests/historical_test_helpers.py`).

### Scope

Pure statistics only, per this module's requirements:

- **No** Machine Learning, forecasting, or prediction (trend detection
  uses closed-form ordinary-least-squares linear regression).
- **No** alerting, reports, authentication, or user management.
- **No** new database tables — reads exclusively through
  `DatabaseService`'s existing repository methods
  (`get_sensor_history`, `get_latest_readings`); the raw
  `sensor_readings` table is never modified.

### Time Windows

`HistoryWindow` (`app/historical/utils.py`) supports `hour` (last
hour), `day` (24h), `week` (7d), `month` (30d), `quarter` (90d), and
`year` (365d) as convenience shortcuts, or an explicit `start`/`end`
custom range — mutually exclusive, validated by
`resolve_time_window()` (`400 Bad Request` on conflicting/invalid
combinations). Neither given defaults to the last 24 hours.

### Statistical Methods

`app/historical/statistics.py` implements, using the Python standard
library only (`statistics`/`math` — no `numpy`/`pandas` dependency,
per this module's "must remain lightweight" requirement): minimum,
maximum, average, median, standard deviation (sample or population),
variance, percent change, first/last value, count, missing-value
count, and trailing rolling mean/rolling standard deviation over a
configurable window (`moving_average` is a named alias of
`rolling_mean`, per this module's "No Duplicate Logic" standard rather
than a second implementation of the same math).

### Trend Algorithms

`app/historical/trends.py`'s `linear_trend()` fits an ordinary
least-squares line through `(elapsed_seconds, value)` points (a closed
-form statistical method, not Machine Learning), yielding a slope,
intercept, and R² (used directly as `trend_confidence`, `0.0`-`1.0`).
`classify_trend()` turns the window's percent change into a
`TrendDirection` — `stable` below a 2% threshold, `rapid_increase`/
`rapid_decrease` at or above a 15% threshold, `increasing`/
`decreasing` in between, or `insufficient_data` with fewer than 2
usable points. `rate_of_change()` converts the raw per-second slope
into a per-hour rate for display.

### Seasonal Grouping

`app/historical/seasonal.py` groups points by hour-of-day (00-23),
day-of-week (Monday-Sunday), ISO calendar week, calendar month,
meteorological season (Northern Hemisphere convention: Dec-Feb
Winter, Mar-May Spring, Jun-Aug Summer, Sep-Nov Autumn — documented in
the module for Southern-Hemisphere deployments), or year, each
summarized with the same statistics functions above.

### Data Aggregation

`app/historical/aggregation.py` buckets points into Hourly/Daily
(UTC)/Weekly (Monday-start ISO week)/Monthly buckets and returns one
summarized `AggregatedBucket` (count/average/min/max/std-dev) per
bucket — read-only; raw sensor readings are never rewritten. Also
powers `comparison.py`'s hourly alignment (see below).

### Parameter Comparison

`app/historical/comparison.py::compare_series()` independently
aggregates two arbitrary parameter series into hourly buckets, pairs
up buckets present in *both* series, and computes their Pearson
correlation coefficient (`[-1.0, 1.0]`, `None` if fewer than 2 aligned
buckets or either series is constant) — usable for any two parameters
(e.g. DO vs Temperature, Conductivity vs TDS, Rainfall vs Water Level,
Water Level vs Flow Velocity), sensor or derived-analytics alike.

### New REST Endpoints

Mounted under the same `/history` prefix as Module 5's existing
`/history/sensor` and `/history/analytics` routes
(`app/api/routers/historical.py`), using the same response envelope
and error conventions as the rest of the REST API:

- `GET /history/statistics/{parameter}?window=&start=&end=&device_name=` —
  minimum, maximum, average, median, standard deviation, variance,
  first/last value, percent change, sample/missing count.
- `GET /history/trends/{parameter}?window=&start=&end=&device_name=` —
  trend direction, trend percentage, rate of change (per hour), fitted
  slope/intercept, and trend confidence.
- `GET /history/seasonal/{parameter}?group_by=&window=&start=&end=&device_name=` —
  grouped summaries (`group_by` defaults to `month`).
- `GET /history/compare?parameter_a=&parameter_b=&window=&start=&end=&device_name=` —
  both parameters' summary statistics plus their correlation; backs
  the dashboard's Comparison Selector. `400` if `parameter_a` equals
  `parameter_b`.

`{parameter}` accepts either a raw sensor's canonical key (e.g.
`dissolved_oxygen`) or a registered analytics parameter key (e.g.
`tds`) — resolved the same way for every endpoint via
`fetch_parameter_series()`. An unknown parameter is a `404`. Hourly/
daily/weekly/monthly aggregation (`HistoricalAnalyticsService.get_aggregation()`)
is implemented and tested but intentionally not yet wired to its own
endpoint — it's a reusable building block for the next (ML) module,
matching the file structure this module was asked to produce.

### Dashboard Integration

The Trends page (`frontend/src/pages/Trends.jsx`) was extended, not
redesigned: it still renders the same `TrendChart` against the
existing `/history/sensor` / `/history/analytics` endpoints, and now
additionally renders a **Statistics Panel** (`StatisticsPanel.jsx` —
Minimum/Maximum/Average/Median/Latest Value cards plus a **Trend
Indicator** chip) from the new `/history/statistics` and
`/history/trends` endpoints, a **Time Range Selector** extended with
90 Days / 1 Year options, and a **Comparison Selector** (a second
sensor dropdown) that renders a `ComparisonPanel.jsx` — averages,
ranges, and a correlation-strength chip — from `/history/compare`
when a comparison sensor is chosen.

### Performance

Bounded for the stated scale (5-second updates, 15-20 sensors, years
of history): `fetch_parameter_series()` pages through
`DatabaseService.get_sensor_history()` in 2,000-row pages and caps
any single request at `MAX_SERIES_POINTS` (20,000) points, logging a
warning if a request's range is truncated, rather than loading an
unbounded number of rows into memory. `compare_series()` reduces both
input series to hourly buckets before correlating, so comparison cost
scales with the number of distinct hours in range, not raw sample
count.

### Testing (Historical Analytics)

```bash
pytest tests/test_historical_statistics.py
pytest tests/test_historical_trends.py
pytest tests/test_historical_aggregation.py   # also covers seasonal.py
pytest tests/test_historical_comparison.py
pytest tests/test_historical_utils.py
pytest tests/test_historical_service.py
pytest tests/test_api_historical.py
```

`test_historical_service.py` and `test_api_historical.py` exercise
`HistoricalAnalyticsService` and its REST endpoints end-to-end against
an isolated in-memory SQLite `DatabaseService`
(`tests/historical_test_helpers.py`), covering: unknown-parameter
`404`s, conflicting time-range `400`s, sensor and analytics-parameter
resolution, empty-range responses, and correlation between two
sensors. Frontend coverage lives alongside the existing dashboard test
suite: `frontend/src/components/HistoricalPanels.test.jsx`
(`TrendIndicator`/`StatisticsPanel`/`ComparisonPanel`) and updated
cases in `frontend/src/services/sensorService.test.js` /
`frontend/src/pages/Trends.test.jsx`.

## Dependencies

Core (used by this module): `fastapi`, `uvicorn`, `pydantic`,
`pydantic-settings`, `python-dotenv`, `PyYAML`, `SQLAlchemy`,
`alembic`, `psycopg2-binary`, `loguru`, `pytest`, `httpx`.

Used by the Analytics Engine: `numpy` (pinned in `requirements.txt`;
`math`/the standard library covers every equation currently
implemented, but `numpy` is available for future analytics work).

Reserved for future modules (already pinned in `requirements.txt` so
the environment is ready): `pyserial`, `pandas`, `scikit-learn`,
`xgboost`.

## Installation

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then edit values as needed
```

You'll need a running PostgreSQL instance (ideally with the
TimescaleDB extension available for future modules) reachable at the
URL configured in `.env` via `DATABASE_URL`. The backend starts even
if the database is unreachable — `/health` will simply report the
`database` component as `degraded`.

## Running the Backend

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Health check: `http://localhost:8000/api/v1/health`

## Running Tests

```bash
pytest
```

## Database Migrations (Alembic)

See [Migration Workflow](#migration-workflow) under
[Database Layer](#database-layer) above. `alembic/env.py` reads the
database URL from `app.config.settings.get_settings()` (not
`alembic.ini`) and imports `app.database.models`, so
`Base.metadata` and the connection string both stay in sync
automatically as models are added.

## Coding Standards

- Full **type hints** on all functions and methods.
- **Google-style docstrings** on every module, class, and function.
- **PEP8** formatting.
- **SOLID principles**: single-responsibility packages, dependency
  injection via FastAPI's `Depends` (see `get_db`), and factory
  functions instead of module-level global state where practical.
- All configuration flows through `app.config.settings.get_settings()`
  — never hardcode environment-dependent values.
- All errors inherit from `app.utils.exceptions.ApplicationError` and
  are translated into the standard `ErrorResponse` envelope by the
  global exception handler in `main.py`.
- All log output goes through `app.utils.logger.get_logger(__name__)`
  — never use bare `print()`.

## Future Modules

This foundation is designed to be extended, not restructured:

1. ~~**Serial Communication** (`app/serial`)~~ — **Implemented.** See
   [Serial Acquisition Subsystem](#serial-acquisition-subsystem)
   above.
2. ~~**Database Layer** (`app/database`)~~ — **Implemented.** See
   [Database Layer](#database-layer) above.
3. ~~**Analytics Engine** (`app/analytics`)~~ — **Implemented.** See
   [Analytics Engine](#analytics-engine) above.
4. ~~**REST API** (`app/api`)~~ — **Implemented.** See
   [REST API](#rest-api) above.
5. ~~**Historical Analytics & Trend Engine** (`app/historical`)~~ —
   **Implemented.** See
   [Historical Analytics & Trend Engine](#historical-analytics--trend-engine)
   above.
6. **Machine Learning** (`app/ml`) — `predictor.py`, `anomaly.py`,
   `pollution_source.py`, likely exposed through a future
   `app/api/routers/prediction.py`, and free to depend directly on
   `HistoricalAnalyticsService` for feature computation rather than
   re-querying `DatabaseService` from scratch.
7. **Reports & Alerts** — report generation and threshold-based
   alerting, likely their own `app/reports`/`app/alerts` packages
   plus corresponding API routers.

Each future module should add files into the folders reserved for it
above; the top-level architecture, configuration system, database
plumbing, logging, and response contracts defined in this foundation
are expected to remain stable throughout the project's lifetime.
