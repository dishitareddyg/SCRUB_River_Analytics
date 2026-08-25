# End-to-End Simulated Test Procedure

Repeatable test procedure for the SCRUB v4 system running entirely in simulation mode (no hardware required).

## Prerequisites

- Python 3.11+ with `pip install -r nav_service/requirements.txt`
- Node.js 18+ with `cd dashboard && npm install`
- No hardware required — everything runs via `SimulatedArduinoLink`

## Test Procedure

### Step 1 — Start the backend in simulate mode

```bash
cd scrub-v4
python -m nav_service.main --config nav_service/config.yaml --simulate
```

Expected output:
```
SimulatedArduinoLink opened
Firebase sync disabled (firebase.enabled=false or SDK missing)
SCRUB v4 nav_service starting...
Uvicorn running on http://0.0.0.0:8000
```

### Step 2 — Verify the health endpoint

In a second terminal:

```bash
curl http://localhost:8000/api/health
```

Expected response:
```json
{"status": "ok", "arduino_link": "connected", "uptime_s": <number>}
```

### Step 3 — Start the frontend dev server

```bash
cd scrub-v4/dashboard
npm run dev
```

Open `http://localhost:5173` in a browser. Click **Mission Control** in the top bar.

### Step 4 — Connect to the backend

1. Click the **Settings** gear icon (top-right).
2. Enter `ws://localhost:8000/ws` as the Pi WebSocket URL.
3. Click **Test** — should show "Connected! Status: ok".
4. Click **Save**.

**Pass criteria**: Connection status indicator in top bar shows "connected" (green dot).

### Step 5 — Place waypoints and send mission

1. Click the **Place** button (top-left of sidebar).
2. Click 3 points on the map to place waypoints.
3. Click **Send Mission (3 waypoints)**.

**Pass criteria**: Backend logs show `load_mission: 3 waypoints loaded`. Frontend waypoints list shows all 3 waypoints.

### Step 6 — Start the mission

1. Click the **Start** button in mission controls.

**Pass criteria**:
- State badge changes from `IDLE` to `RUNNING`.
- Boat marker appears on the map and starts moving toward waypoint 1.
- Telemetry panel shows live sensor values updating at ~3 Hz.
- Backend logs show `nav_tick` execution and motor commands.

### Step 7 — Verify DWELL state

Wait for the boat to reach waypoint 1 (~30-60 seconds in simulation).

**Pass criteria**:
- State badge changes to `DWELL`.
- Dwell view appears with countdown timer (30s).
- Live sensor samples stream in every 2 seconds.
- Sample count increments.
- Running averages update in real time.

After 30 seconds:
- State transitions back to `RUNNING`.
- Waypoint 1 shows as "DONE" in the waypoint list.
- Boat marker starts moving toward waypoint 2.

### Step 8 — Verify full mission cycle

Wait for all 3 waypoints to be visited.

**Pass criteria**:
- After waypoint 3: State changes to `COMPLETE`.
- Backend logs show `COMPLETE: all waypoints reached`.
- Backend logs show `SQLite mission status update: COMPLETE`.

### Step 9 — Verify mission history

1. Click the **History** button (top-right).

**Pass criteria**:
- Mission #1 appears with status "COMPLETE".
- Clicking it shows 3 waypoint results.
- Each waypoint shows averaged sensor values (ph, tds, turb, wtemp, atemp, hum).
- Sample count is approximately 15 (30s / 2s interval).

### Step 10 — Verify REST API

```bash
curl http://localhost:8000/api/missions
curl http://localhost:8000/api/missions/1/waypoints
curl http://localhost:8000/api/missions/1/dwell_samples
```

**Pass criteria**:
- `/api/missions` returns array with one mission, status "COMPLETE".
- `/api/missions/1/waypoints` returns 3 waypoint results with avg_sensors.
- `/api/missions/1/dwell_samples` returns raw sensor samples.

### Step 11 — Test manual override toggle

1. During a running mission, click **Manual Override**.
2. Toggle it on, then off.

**Pass criteria**:
- When ON: effective_mode shows "MANUAL", mission controls disable.
- When OFF: effective_mode returns "AUTO", controls re-enable.
- Backend logs show `Dashboard override: ENABLED/DISABLED`.

### Step 12 — Test Emergency Stop

1. During a running mission, click **E-Stop**.

**Pass criteria**:
- State changes to `STOPPED` immediately.
- Motors set to 0/0.
- Backend logs show `emergency stop`.

### Step 13 — Test disconnect/reconnect

1. Kill the backend process (Ctrl+C in backend terminal).
2. Wait 3-5 seconds.

**Pass criteria**:
- Frontend connection status changes to "offline" (red dot).
- No stale data is displayed.

3. Restart the backend: `python -m nav_service.main --config nav_service/config.yaml --simulate`

**Pass criteria**:
- Frontend auto-reconnects within 3-30 seconds (exponential backoff).
- Connection status returns to "connected" (green dot).
- Telemetry resumes.

## Latency Measurements

### Command dispatch latency
Backend logs (with `DEBUG` level) show command dispatch time. Expected: < 5 ms.

### Telemetry build latency
Backend logs show telemetry build time. Expected: < 30 ms.

### Motor heartbeat independence
The motor heartbeat runs at 5 Hz (0.2s interval) independently of the 4s nav tick. Confirmed by debug logs showing consistent tick count regardless of nav tick timing.

### Firebase isolation
With Firebase disabled (`firebase.enabled: false`) or with invalid credentials, telemetry broadcast and motor commands are unaffected. Firebase push errors are logged but never block the main loops.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Connection stays "offline" | Backend not running or wrong URL | Check backend is running, verify URL in settings |
| Boat doesn't move | Manual mode active | Check effective_mode, toggle manual override off |
| No dwell samples | Boat hasn't reached waypoint | Wait for arrival, check arrival_radius_m |
| History shows "RUNNING" | Mission status not updated | Ensure using latest code (mission status fix applied) |
| Mapbox doesn't load | Missing API token | Check VITE_LOVABLE_CONNECTOR_MAPBOX_PUBLIC_TOKEN env var |
