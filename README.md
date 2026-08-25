# SCRUB v4 — Autonomous Lake Water Quality Monitoring Boat

GPS-guided waypoint missions with live sensor telemetry, manual RC override, and Firebase-backed remote mission history. Runs a Python/asyncio backend on Raspberry Pi 5 with a React dashboard frontend, communicating over WebSocket and REST.

## Repo Layout

```
scrub-v4/
├── nav_service/        # Python backend (runs on Pi 5)
│   ├── main.py         # CLI entrypoint, task wiring
│   ├── server.py       # FastAPI app (WS + REST)
│   ├── navigation.py   # State machine + steering math
│   ├── arduino_link.py # UART link (real + simulated)
│   ├── safety.py       # Geofence, watchdog, timer
│   ├── logger.py       # SQLite telemetry logger
│   ├── firebase_sync.py # Optional Firebase RTDB mirror
│   ├── config.yaml     # Configuration
│   └── requirements.txt
├── dashboard/          # React frontend (TanStack Start + Mapbox)
│   ├── src/
│   │   ├── hooks/use-live-telemetry.ts  # WebSocket hook
│   │   ├── routes/mission.tsx           # Mission Control page
│   │   └── components/mission/          # Mission UI components
│   ├── FRONTEND_README.md
│   └── package.json
├── docs/
│   ├── e2e_simulated_test.md   # End-to-end test procedure
│   └── hardware_bringup.md     # Real-hardware wiring + bring-up
├── BACKEND_README.md   # Backend API, protocol, architecture
└── FUTURE_IDEAS.md     # Deferred features
```

## Quickstart

Get from zero to a working simulated mission in under 10 commands:

```bash
# 1. Clone and enter the project
cd scrub-v4

# 2. Install backend dependencies
pip install -r nav_service/requirements.txt

# 3. Start the backend in simulate mode
python -m nav_service.main --config nav_service/config.yaml --simulate

# 4. (In a second terminal) Install frontend dependencies
cd dashboard && npm install

# 5. Start the frontend dev server
npm run dev

# 6. Open http://localhost:5173 in your browser
# 7. Click "Mission Control" in the top bar
# 8. Click the Settings gear → enter ws://localhost:8000/ws → Test → Save
# 9. Click "Place" → click 3 points on the map → "Send Mission"
# 10. Click "Start" — watch the boat navigate through waypoints
```

## Architecture at a Glance

```
┌─────────────────────────────────────────────────────────────────────┐
│  Arduino (sensors + GPS + compass + RC + motors)                    │
│  └─ Reads sensors, GPS, compass, RC; drives motors                 │
└────────────────────────┬────────────────────────────────────────────┘
                         │ UART JSON (115200 baud, newline-delimited)
                         │ {"gps":{...}, "hdg":187.5, "sensors":{...}}
                         │ {"cmd":"motor", "l":18, "r":22}
┌────────────────────────┴────────────────────────────────────────────┐
│  Raspberry Pi 5 — nav_service (Python/asyncio)                     │
│  └─ FastAPI: nav state machine, SQLite logger, Firebase sync       │
│     ├─ nav_decision_task (4s)     — compute heading/power          │
│     ├─ motor_heartbeat_task (0.2s)— send power to Arduino          │
│     ├─ ws_broadcast_task (0.33s)  — stream telemetry to dashboard  │
│     └─ firebase_consumer          — optional Firebase RTDB mirror    │
└────────────────────────┬────────────────────────────────────────────┘
                         │ WebSocket + REST (LAN)
                         │ ws://<pi_ip>:8000/ws
                         │ GET /api/health, /api/missions
┌────────────────────────┴────────────────────────────────────────────┐
│  Browser Dashboard (React + TanStack Start + Mapbox GL)            │
│  └─ Mission Control: waypoint planner, live boat tracking,         │
│     mission controls, dwell view, history, manual override         │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Concepts

- **State machine**: `IDLE → RUNNING → DWELL → RUNNING → ... → COMPLETE` with safety states (`GPS_LOST`, `GEOFENCE_STOP`, `STOPPED`, `MANUAL`)
- **Dwell sampling**: At each waypoint, the boat stops for 30s and collects ~15 sensor samples (every 2s), then averages them before advancing
- **Manual override**: Two independent sources — physical RC switch on Arduino AND dashboard toggle — either one asserts `MANUAL` mode
- **Safety layers**: Geofence, GPS watchdog, mission timer, emergency stop — all independent of the main nav loop

## Documentation

- [BACKEND_README.md](BACKEND_README.md) — API reference, wire protocol, state machine, config
- [FRONTEND_README.md](dashboard/FRONTEND_README.md) — Routes, components, architecture
- [docs/hardware_bringup.md](docs/hardware_bringup.md) — Wiring checklist, UART setup, safety notes
- [docs/e2e_simulated_test.md](docs/e2e_simulated_test.md) — Repeatable test procedure with results
- [FUTURE_IDEAS.md](dashboard/FUTURE_IDEAS.md) — Deferred features (fleet support, video, mobile app, etc.)

## Known Limitations / Deliberately Deferred

- **Single boat only** — no fleet coordination or multi-boat missions
- **No video streaming** — camera integration deferred to future iteration
- **No push notifications** — alerts only visible in dashboard
- **No user auth** — single-user system, no login required
- **No offline map tiles** — requires internet for Mapbox tiles
- **No mobile native app** — web dashboard only
- **No autonomous path planning** — manual waypoint placement only
- **No CSV/PDF export** — data accessible via SQLite and REST API
