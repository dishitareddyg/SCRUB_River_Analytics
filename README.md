# Lake Bot Autonomous Navigation & River Analytics Service (`autonomous_nav`)

## 1. Overview & Architecture

This service combines the autonomous waypoint navigation logic of `nav_service` with the robust sensor acquisition, local caching, and cloud sync architecture of `new sensor/SCRUB_River_Analytics`.

### Key System Characteristics
1. **Single Microcontroller Link (STM32 over UART):**
   - **Incoming (0.5 Hz):** STM32 relays all sensor readings, NEO-M8N GPS (`latitude`, `longitude`), compass (`heading`), and motor status (`motors.left`, `motors.right`).
   - **Outgoing (configurable, default 2.0 s):** RPi sends motor PWM commands directly back to the STM32 via the same serial port:
     ```json
     {"left":"+150","right":"+105","mode":"auto"}
     ```
   - Hardware accepts PWM from **-999 to +999**.
   - Power ceiling and command frequency are globally configurable via environment variables (`MAX_MOTOR_POWER`, `NAV_COMMAND_INTERVAL_S`).

2. **Frontend-Driven Grid Missions via Supabase:**
   - Frontend creates an autonomous mission with ordered grid targets.
   - Bot fetches mission waypoints from Supabase (`missions` & `mission_grids`).
   - Navigates toward the center of each grid using proportional differential steering.

3. **Autonomous Grid Collection & Hand-off:**
   - When the bot enters within the configured radius of the grid center (`WAYPOINT_ARRIVAL_RADIUS_M`, default 5.0 m):
     1. Motors are stopped (`left=0, right=0`).
     2. Navigator transitions from `NAVIGATING` to `COLLECTING`.
     3. Navigator notifies `MeasurementManager`.
     4. `MeasurementManager` gates sensor sampling (requires `motor_state == IDLE`, GPS fresh, within grid radius) every `SENSOR_SAMPLE_INTERVAL_SECONDS` (default 6 s).
     5. Accepted samples are saved in local SQLite with atomic 5-step transaction.
     6. Once `MAX_READINGS_PER_GRID` (default 10) samples are collected, the session is completed and the local average is computed.
     7. `MeasurementManager` signals `navigator.on_grid_collection_complete()`.
     8. Navigator transitions back to `NAVIGATING` towards the next grid point until all grids are visited.

4. **Decoupled Cloud Upload & Verification:**
   - `UploaderWorker` runs independently in the background.
   - Batch uploads samples to Supabase (`grid_sessions` and `sensor_samples`).
   - Verifies directly against Supabase that all samples are confirmed present before marking the session complete in the cloud and purging the local SQLite buffer.

---

## 2. Directory Structure

```
autonomous_nav/
├── cloud/
│   ├── supabase_client.py       # Supabase REST client (grids, missions, sessions, samples)
│   └── uploader.py              # Decoupled batch uploader with cloud completion verification
├── communication/
│   └── mqtt_client.py           # Auto-reconnecting MQTT telemetry publisher
├── config/
│   └── settings.py              # Central frozen dataclass with all tunable knobs
├── hardware/
│   ├── gps.py                   # In-memory GPS fix and compass heading tracker
│   ├── motor_controller.py      # Motor state tracker & RPi->STM32 command writer
│   └── stm32.py                 # Bidirectional UART worker with shared serial write lock
├── measurement/
│   ├── grid_matcher.py          # Haversine nearest-grid matcher & Supabase grid sync
│   ├── measurement_manager.py   # Central sensor pipeline and Navigator hand-off
│   ├── sensor_validator.py      # Per-field validator with NULL coercion for out-of-range values
│   └── session_manager.py       # Active session lookup and lifecycle manager
├── migrations/
│   └── 0002_autonomous_mission_schema.sql  # SQL schema for missions and mission_grids
├── monitoring/
│   ├── health.py                # Internal health snapshot publisher
│   └── logger.py                # Standardized logger
├── navigation/
│   ├── mission_manager.py       # Polls Supabase for PENDING missions and updates grid status
│   ├── navigator.py             # 8-state navigation state machine and steering loop
│   └── steering.py              # Pure geo math (haversine, bearing, proportional mixer)
├── storage/
│   ├── buffer_manager.py        # Buffer management interface
│   └── sqlite_manager.py        # WAL-mode SQLite storage with atomic sample commits
├── systemd/
│   └── lake-bot-autonomous.service
├── tests/
│   └── test_autonomous_pipeline.py # Unit tests for steering, packets, and hand-off
├── .env.example
├── main.py                      # Application entrypoint
├── requirements.txt
└── README.md
```

---

## 3. Configuration & Tunables for Electronics Team

Set in `.env` (or environment variables):

| Variable | Default | Purpose |
|---|---|---|
| `MAX_MOTOR_POWER` | `300` | Absolute ceiling for PWM sent to STM32 (hardware range: -999 to +999) |
| `NAV_COMMAND_INTERVAL_S` | `2.0` | How often RPi sends `{"left":..., "right":..., "mode":"auto"}` to STM32 |
| `DEFAULT_CRUISE_POWER` | `150` | Base forward PWM when heading error is zero |
| `STEERING_K` | `1.5` | Proportional steering multiplier (`pwm = cruise ± K * error_deg`) |
| `WAYPOINT_ARRIVAL_RADIUS_M` | `5.0` | Distance (metres) to grid center to declare arrival |
| `GEOFENCE_RADIUS_M` | `500.0` | Max distance from start position before safety halt (0 to disable) |
| `GPS_LOSS_TIMEOUT_S` | `10.0` | Seconds without GPS fix while navigating before safety stop |
| `STM32_SERIAL_PORT` | `/dev/ttyAMA1` | UART port connected to STM32 |
| `STM32_BAUDRATE` | `115200` | UART baudrate |

---

## 4. STM32 UART Packet Protocols

### Incoming (STM32 → RPi 5 at ~0.5 Hz):
```json
{
  "device_id": "BOT001",
  "timestamp": "2026-09-28T06:00:00Z",
  "motors": {"left": 0, "right": 0},
  "gps": {"latitude": 12.916860, "longitude": 77.486980},
  "compass": {"heading": 182.4},
  "sensors": {
    "ph": 7.12,
    "tds": 214.2,
    "turbidity": 15.3,
    "temperature_c": 27.4,
    "humidity_percent": 71.2
  }
}
```

### Outgoing (RPi 5 → STM32 every `NAV_COMMAND_INTERVAL_S`):
```json
{"left":"+150","right":"+105","mode":"auto"}
```
- Signs are explicit (`+` for forward, `-` for reverse).
- Stopped command: `{"left":"+0","right":"+0","mode":"auto"}`.

---

## 5. Supabase Database Schema

### Existing Tables (from your DB schema):
- `lakes`: Lake boundaries and metadata.
- `grids`: Grid cells with `center_lat`, `center_lon`, `grid_size_m`.
- `grid_sessions`: Active and completed measurement sessions per grid.
- `sensor_samples`: Raw sensor readings with `session_id`, `grid_id`, and `sample_number`.

### New Tables for Autonomous Missions (`migrations/0002_autonomous_mission_schema.sql`):
1. **`missions`**:
   - `mission_id` (UUID PK)
   - `device_id` (TEXT)
   - `lake_id` (UUID FK)
   - `status` ('PENDING', 'ACTIVE', 'PAUSED', 'COMPLETED', 'ABORTED')
   - `created_at`, `started_at`, `completed_at`
2. **`mission_grids`**:
   - `mission_grid_id` (UUID PK)
   - `mission_id` (UUID FK)
   - `grid_id` (UUID FK)
   - `sequence_order` (INT2) — Order in which the bot will visit the grids
   - `status` ('PENDING', 'NAVIGATING', 'COLLECTING', 'COMPLETED', 'SKIPPED')
   - `session_id` (UUID FK to `grid_sessions`)

---

## 6. How to Run

### Install Dependencies:
```bash
pip install -r requirements.txt
```

### Configure `.env`:
```bash
cp .env.example .env
# Edit SUPABASE_URL, SUPABASE_KEY, and STM32_SERIAL_PORT
```

### Run Tests:
```bash
python -m unittest discover tests
```

### Start Service:
```bash
python main.py
```

### Systemd Deployment (Raspberry Pi):
```bash
sudo cp systemd/lake-bot-autonomous.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable lake-bot-autonomous
sudo systemctl start lake-bot-autonomous
```
