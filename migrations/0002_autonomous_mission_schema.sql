-- ============================================================================
-- 0002_autonomous_mission_schema.sql
--
-- Autonomous Navigation & Mission Extension for Supabase
--
-- Adds support for frontend-driven autonomous missions where the frontend
-- specifies an ordered sequence of target grids for the Lake Bot to visit,
-- stop at, sample, and complete.
-- ============================================================================

-- Enable pgcrypto / uuid-ossp if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ----------------------------------------------------------------------------
-- 1. Table: missions
-- Represents an autonomous mission dispatched to a bot.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS missions (
    mission_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id       TEXT NOT NULL,
    lake_id         UUID REFERENCES lakes(lake_id) ON DELETE SET NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING', 'ACTIVE', 'PAUSED', 'COMPLETED', 'ABORTED')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    notes           TEXT
);

CREATE INDEX IF NOT EXISTS idx_missions_device_status
    ON missions(device_id, status);

-- ----------------------------------------------------------------------------
-- 2. Table: mission_grids
-- Ordered sequence of grid points that the bot will autonomously navigate to.
-- Each entry links to the grid definition in `grids`.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mission_grids (
    mission_grid_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mission_id      UUID NOT NULL REFERENCES missions(mission_id) ON DELETE CASCADE,
    grid_id         UUID NOT NULL REFERENCES grids(grid_id) ON DELETE CASCADE,
    sequence_order  INT2 NOT NULL,
    status          TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (status IN ('PENDING', 'NAVIGATING', 'COLLECTING', 'COMPLETED', 'SKIPPED')),
    session_id      UUID REFERENCES grid_sessions(session_id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (mission_id, sequence_order)
);

CREATE INDEX IF NOT EXISTS idx_mission_grids_mission_seq
    ON mission_grids(mission_id, sequence_order);

-- ----------------------------------------------------------------------------
-- Helper View: active_mission_progress
-- Allows frontend to view real-time mission status, targets, and coordinates.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE VIEW active_mission_progress AS
SELECT
    m.mission_id,
    m.device_id,
    m.status AS mission_status,
    m.started_at,
    mg.sequence_order,
    mg.status AS grid_nav_status,
    g.grid_id,
    g.grid_code,
    g.center_lat,
    g.center_lon,
    mg.session_id,
    gs.sample_count,
    gs.completed_at AS session_completed_at
FROM missions m
JOIN mission_grids mg ON m.mission_id = mg.mission_id
JOIN grids g ON mg.grid_id = g.grid_id
LEFT JOIN grid_sessions gs ON mg.session_id = gs.session_id
ORDER BY m.mission_id, mg.sequence_order;
