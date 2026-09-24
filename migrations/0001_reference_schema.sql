-- ============================================================
-- 0001_reference_schema.sql
--
-- Reference schema matching the EXISTING Supabase database described
-- in the project specification. This backend does NOT require any
-- changes to this schema -- it is provided so a fresh Supabase project
-- can be initialized identically if ever needed (e.g. staging/test
-- environment), and so the unique constraints this backend relies on
-- for idempotent upserts are documented in one place.
--
-- Safe to run on a fresh project (uses IF NOT EXISTS). Do NOT run this
-- against the existing production project if the tables already exist
-- with this shape -- it is a no-op in that case anyway.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS lakes (
    lake_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name          TEXT NOT NULL,
    boundary_geom GEOMETRY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS grids (
    grid_id       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    lake_id       UUID NOT NULL REFERENCES lakes(lake_id),
    grid_code     TEXT NOT NULL UNIQUE,
    grid_size_m   NUMERIC NOT NULL DEFAULT 5,
    center_lat    DOUBLE PRECISION NOT NULL,
    center_lon    DOUBLE PRECISION NOT NULL,
    center_geom   GEOMETRY(Point, 4326),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS measurement_sessions (
    session_id     UUID PRIMARY KEY,
    grid_id        UUID NOT NULL REFERENCES grids(grid_id),
    device_id      TEXT NOT NULL,
    started_at     TIMESTAMPTZ NOT NULL,
    completed_at   TIMESTAMPTZ,
    latitude       DOUBLE PRECISION,
    longitude      DOUBLE PRECISION,
    position_geom  GEOMETRY(Point, 4326),
    sample_count   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_measurement_sessions_grid ON measurement_sessions(grid_id);

CREATE TABLE IF NOT EXISTS sensor_readings (
    reading_id         UUID PRIMARY KEY,
    session_id         UUID NOT NULL REFERENCES measurement_sessions(session_id),
    grid_id            UUID NOT NULL REFERENCES grids(grid_id),
    sample_number      SMALLINT NOT NULL CHECK (sample_number BETWEEN 1 AND 10),
    recorded_at        TIMESTAMPTZ NOT NULL,
    latitude           DOUBLE PRECISION,
    longitude          DOUBLE PRECISION,
    position_geom      GEOMETRY(Point, 4326),
    ph                 NUMERIC,
    tds                NUMERIC,
    turbidity          NUMERIC,
    temperature_c      NUMERIC,
    humidity_percent   NUMERIC,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(session_id, sample_number)
);

CREATE INDEX IF NOT EXISTS idx_sensor_readings_session ON sensor_readings(session_id);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_grid ON sensor_readings(grid_id);

-- Note: sample_number's upper bound (10 above) mirrors the DB-level check
-- matching MAX_READINGS_PER_GRID's *default* of 10. If MAX_READINGS_PER_GRID
-- is changed in config/settings.py, update this CHECK constraint to match,
-- or relax it to a generic positive-integer check and let the application
-- layer be the single source of truth for the maximum.
