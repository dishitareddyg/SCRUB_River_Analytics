-- ============================================================================
-- 0003_polygon_navigation_schema.sql
--
-- Global polygon (boustrophedon) navigation + GPS-tagged sensor readings.
-- Canonical schema: docs/supabase_schema.webp + docs/SUPABASE_SCHEMA.md
-- (shared by backend and frontend — same table and column names).
-- Idempotent: safe on a fresh project or on top of 0002 (grid missions).
-- Review against the DEPLOYED schema before running (it is the source of
-- truth); every statement only adds or relaxes, nothing is dropped.
--
-- Grid analysis is FUTURE work: raw readings keep position_geom (SRID 4326)
-- so they can be classified into lake grid cells later with ST_Contains.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ----------------------------------------------------------------------------
-- lakes
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lakes (
    lake_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name           TEXT NOT NULL,
    boundary_geom  geometry(Polygon, 4326),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE lakes ADD COLUMN IF NOT EXISTS boundary_geom geometry(Polygon, 4326);

-- ----------------------------------------------------------------------------
-- missions
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS missions (
    mission_id      UUID PRIMARY KEY,
    device_id       TEXT NOT NULL,
    lake_id         UUID REFERENCES lakes(lake_id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    notes           TEXT
);
ALTER TABLE missions ADD COLUMN IF NOT EXISTS polygon_geom geometry(Polygon, 4326);
ALTER TABLE missions ADD COLUMN IF NOT EXISTS waypoint_load_ack BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE missions ADD COLUMN IF NOT EXISTS total_waypoints INTEGER NOT NULL DEFAULT 0;
ALTER TABLE missions ADD COLUMN IF NOT EXISTS current_waypoint_index INTEGER NOT NULL DEFAULT 0;
ALTER TABLE missions ADD COLUMN IF NOT EXISTS progress_percent NUMERIC(5,2) NOT NULL DEFAULT 0;
ALTER TABLE missions ADD COLUMN IF NOT EXISTS notes TEXT;

-- Replace the 0002 status check with the full lifecycle.
ALTER TABLE missions DROP CONSTRAINT IF EXISTS missions_status_check;
ALTER TABLE missions ADD CONSTRAINT missions_status_check CHECK (status IN (
    'PENDING','LOADING_WAYPOINTS','READY','ACTIVE','PAUSED','COMPLETED','ABORTED','FAILED'));

CREATE INDEX IF NOT EXISTS idx_missions_device_status ON missions(device_id, status);
CREATE INDEX IF NOT EXISTS idx_missions_polygon_gix ON missions USING GIST (polygon_geom);

-- ----------------------------------------------------------------------------
-- mission_waypoints  (GCS -> polygon traversal -> GCS)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mission_waypoints (
    waypoint_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id      UUID NOT NULL REFERENCES missions(mission_id) ON DELETE CASCADE,
    sequence_order  INTEGER NOT NULL,
    latitude        DOUBLE PRECISION NOT NULL,
    longitude       DOUBLE PRECISION NOT NULL,
    waypoint_geom   geometry(Point, 4326),
    status          TEXT NOT NULL DEFAULT 'PENDING',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT mission_waypoints_mission_seq_key UNIQUE (mission_id, sequence_order)
);
CREATE INDEX IF NOT EXISTS idx_mission_waypoints_gix ON mission_waypoints USING GIST (waypoint_geom);
ALTER TABLE mission_waypoints DROP CONSTRAINT IF EXISTS mission_waypoints_status_check;
ALTER TABLE mission_waypoints ADD CONSTRAINT mission_waypoints_status_check
    CHECK (status IN ('PENDING','ACTIVE','COMPLETED','SKIPPED'));

-- ----------------------------------------------------------------------------
-- sensor_readings  (one row per 10 s snapshot, idempotent on local_record_id)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sensor_readings (
    reading_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    local_record_id   UUID NOT NULL,
    mission_id        UUID REFERENCES missions(mission_id) ON DELETE SET NULL,
    device_id         TEXT NOT NULL,
    recorded_at       TIMESTAMPTZ NOT NULL,
    latitude          DOUBLE PRECISION,
    longitude         DOUBLE PRECISION,
    position_geom     geometry(Point, 4326),
    heading           DOUBLE PRECISION,
    ph                NUMERIC,
    tds               NUMERIC,
    turbidity         NUMERIC,
    temperature_c     NUMERIC,
    humidity_percent  NUMERIC,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Upgrade path for an existing (grid-era) sensor_readings table.
ALTER TABLE sensor_readings ADD COLUMN IF NOT EXISTS local_record_id UUID;
ALTER TABLE sensor_readings ADD COLUMN IF NOT EXISTS mission_id UUID;
ALTER TABLE sensor_readings ADD COLUMN IF NOT EXISTS device_id TEXT;
ALTER TABLE sensor_readings ADD COLUMN IF NOT EXISTS position_geom geometry(Point, 4326);
ALTER TABLE sensor_readings ADD COLUMN IF NOT EXISTS heading DOUBLE PRECISION;
DO $$
DECLARE col text;
BEGIN
    -- Grid-era columns must not block grid-free inserts.
    FOREACH col IN ARRAY ARRAY['session_id','grid_id','sample_number'] LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'sensor_readings'
                     AND column_name = col AND is_nullable = 'NO') THEN
            EXECUTE format('ALTER TABLE sensor_readings ALTER COLUMN %I DROP NOT NULL', col);
        END IF;
    END LOOP;
    -- Sensor & GPS values are nullable (missing sensor / no GPS fix).
    FOREACH col IN ARRAY ARRAY['latitude','longitude','ph','tds','turbidity','temperature_c','humidity_percent'] LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema = 'public' AND table_name = 'sensor_readings'
                     AND column_name = col AND is_nullable = 'NO') THEN
            EXECUTE format('ALTER TABLE sensor_readings ALTER COLUMN %I DROP NOT NULL', col);
        END IF;
    END LOOP;
    -- Legacy reading_id without a default would reject inserts from the Pi.
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'sensor_readings'
                 AND column_name = 'reading_id' AND data_type = 'uuid' AND column_default IS NULL) THEN
        ALTER TABLE sensor_readings ALTER COLUMN reading_id SET DEFAULT gen_random_uuid();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sensor_readings_local_record_id_key') THEN
        ALTER TABLE sensor_readings ADD CONSTRAINT sensor_readings_local_record_id_key UNIQUE (local_record_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'sensor_readings_mission_id_fkey') THEN
        ALTER TABLE sensor_readings ADD CONSTRAINT sensor_readings_mission_id_fkey
            FOREIGN KEY (mission_id) REFERENCES missions(mission_id) ON DELETE SET NULL;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_sensor_readings_mission_time ON sensor_readings(mission_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_sensor_readings_gix ON sensor_readings USING GIST (position_geom);

-- Fill geometry from lat/lon when a client does not send EWKT.
CREATE OR REPLACE FUNCTION set_point_geom_from_latlon() RETURNS trigger AS $$
BEGIN
    IF TG_TABLE_NAME = 'sensor_readings' THEN
        IF NEW.position_geom IS NULL AND NEW.latitude IS NOT NULL AND NEW.longitude IS NOT NULL THEN
            NEW.position_geom := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
        END IF;
    ELSIF TG_TABLE_NAME = 'mission_waypoints' THEN
        IF NEW.waypoint_geom IS NULL THEN
            NEW.waypoint_geom := ST_SetSRID(ST_MakePoint(NEW.longitude, NEW.latitude), 4326);
        END IF;
    END IF;
    RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_sensor_readings_geom ON sensor_readings;
CREATE TRIGGER trg_sensor_readings_geom BEFORE INSERT OR UPDATE ON sensor_readings
    FOR EACH ROW EXECUTE FUNCTION set_point_geom_from_latlon();
DROP TRIGGER IF EXISTS trg_mission_waypoints_geom ON mission_waypoints;
CREATE TRIGGER trg_mission_waypoints_geom BEFORE INSERT OR UPDATE ON mission_waypoints
    FOR EACH ROW EXECUTE FUNCTION set_point_geom_from_latlon();

-- RLS (OPT-IN — uncomment after confirming no existing client writes these
-- tables with the anon key): dashboard reads, only the Pi (service role) writes.
-- ALTER TABLE missions ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE mission_waypoints ENABLE ROW LEVEL SECURITY;
-- ALTER TABLE sensor_readings ENABLE ROW LEVEL SECURITY;
-- DROP POLICY IF EXISTS missions_read ON missions;
-- CREATE POLICY missions_read ON missions FOR SELECT USING (true);
-- DROP POLICY IF EXISTS mission_waypoints_read ON mission_waypoints;
-- CREATE POLICY mission_waypoints_read ON mission_waypoints FOR SELECT USING (true);
-- DROP POLICY IF EXISTS sensor_readings_read ON sensor_readings;
-- CREATE POLICY sensor_readings_read ON sensor_readings FOR SELECT USING (true);


-- ----------------------------------------------------------------------------
-- FUTURE (not used by navigation): per-grid averages, e.g.
--   SELECT g.grid_id, avg(r.ph) FROM lake_grid_cells g
--   JOIN sensor_readings r ON ST_Contains(g.cell_geom, r.position_geom)
--   WHERE r.mission_id = $1 GROUP BY g.grid_id;
-- ----------------------------------------------------------------------------
