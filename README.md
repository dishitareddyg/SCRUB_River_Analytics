# Lake Bot — Autonomous Navigation & Water-Quality Backend (`autonomous_nav`)

Runs on the **Raspberry Pi 5**. The STM32 keeps the sensor suite, GPS, compass and motor drivers;
the Pi executes missions: **GCS → polygon (boustrophedon) traversal → GCS**.

```
Frontend (Vercel) ──HTTPS/WSS──► FastAPI on RPi 5 ──UART──► STM32 ── sensors, GPS, compass, motors
                                     │
                     SQLite (source of truth) ──► Supabase (offline-first, ≤1 record / 10 s)
                                     └──► MQTT live telemetry
```

> **Supabase schema (shared by backend and frontend):** [docs/SUPABASE_SCHEMA.md](docs/SUPABASE_SCHEMA.md)
> (diagram: [docs/supabase_schema.webp](docs/supabase_schema.webp)). Use exactly these table and column names.

## 1. UART contract (SOFTWARE ARCHITECTURE.docx — unchanged)

| Direction | Packet | Rate |
|---|---|---|
| STM32 → RPi | `{"device_id":"BOT001","timestamp":"…","motors":{"left":L,"right":R},"gps":{"latitude":lat,"longitude":lon},"compass":{"heading":hdg},"sensors":{"ph":ph,"tds":tds,"turbidity":turb,"temperature_c":temp,"humidity_percent":hum}}` | 1 / 2 s |
| RPi → STM32 | `{"left":"+100","right":"+100","mode":"auto"}` | 1 / 2 s |

* Parser: `hardware/protocol.py::parse_stm32_packet` (exact nested keys; null / NaN / bool / out-of-range → `None`;
  `(0,0)` treated as no fix).
* Generator: `hardware/protocol.py::build_motor_command` (explicit sign, clamped to `±MAX_MOTOR_POWER`, never beyond ±999).
* `MotorControllerWorker` transmits exactly one packet per `MOTOR_COMMAND_INTERVAL_S` (zeros when idle).
  Emergency stop / pause additionally writes an immediate `"+0"` packet.
* `STM32Worker`: line buffering, partial packets, malformed JSON discard, 8 KB overflow guard,
  auto-reconnect, shared write lock, link-alive tracking (`STM32_LINK_TIMEOUT_S`).

## 2. Mission flow

1. `POST /api/missions` → `mission/validator.py` (UUID, device id, coordinate ranges, polygon ≥3 vertices,
   non-self-intersecting, non-zero area, contiguous unique `sequence_order` 0..N-1, first and last waypoint
   type `GCS` matching `ground_control`, COVERAGE points inside the polygon).
2. `PENDING → LOADING_WAYPOINTS`: mission + waypoints are written in one SQLite transaction, then
   `waypoints.json` is written atomically (temp file → fsync → `os.replace`).
3. Counts in SQLite and the JSON file are verified, then the mission becomes `READY` with `waypoint_load_ack=true` and the ack is returned.
4. `POST /api/missions/{id}/start` (explicit authorisation; requires live STM32 link + fresh GPS/compass) → `ACTIVE`.
5. `Navigator` (every `NAV_UPDATE_INTERVAL_S`) does: distance, bearing, heading error, the proportional differential
   mixer (`steering.py`), then sets the desired command. It advances on arrival (`WAYPOINT_ARRIVAL_RADIUS_M`); after the final GCS
   waypoint it sets motors to 0 and the mission becomes `COMPLETED`.

Safety: if GPS is stale, the compass is missing or the STM32 link is lost, the navigator holds (motors 0). If that lasts longer than `GPS_LOSS_TIMEOUT_S`,
the mission is auto-`PAUSED`. Geofence (`GEOFENCE_RADIUS_M` from GCS) and `WAYPOINT_TIMEOUT_S` also cause `PAUSED`.
`MAX_MISSION_RUNTIME_S` and internal errors cause `FAILED`. Navigation only reads SQLite; it never needs Supabase.

**Reboot recovery:** missions left `ACTIVE` become `PAUSED` ("operator must resume"). Interrupted loads become `FAILED`.
Motors are never restarted automatically.

States: `PENDING, LOADING_WAYPOINTS, READY, ACTIVE, PAUSED, COMPLETED, ABORTED, FAILED`.

## 3. Sensor storage — one snapshot every 10 s

`measurement/snapshot_worker.py` stores the latest in-memory readings every `SENSOR_STORE_INTERVAL_S`
(not every 2 s packet). Each snapshot has a new `local_record_id`, the active `mission_id` (or NULL), the device id,
`recorded_at`, the STM32 `hardware_timestamp`, the GPS position and the heading.
If the fix is stale or missing, latitude and longitude are stored as **NULL** with `gps_valid=0` and `gps_age_seconds`, so stale positions are never attached.
NULL sensor values are kept. A snapshot is skipped only when no STM32 packet arrived within `SENSOR_MAX_AGE_S`.

## 4. Offline-first cloud sync

* `SensorUploader`: **at most one record per 10 s** (start-to-start, hard floor of 10 s), oldest `recorded_at` first,
  never concurrent and no bursts after reconnecting. It runs a TCP connectivity probe first, then an idempotent upsert on `local_record_id` with
  read-back confirmation. On failure the record becomes `FAILED` and is retried with exponential back-off (`UPLOAD_RETRY_*`). Records are never deleted.
  Records of a mission wait until the mission row exists in the cloud (foreign key).
* `MissionSyncWorker`: upserts mission status, progress and polygon (`polygon_geom`) whenever the local `cloud_version`
  changes, the waypoint list once, then every waypoint status change (`UNIQUE(mission_id, sequence_order)`).
* Geometry is sent as EWKT (`SRID=4326;POINT(lon lat)`). The migration also fills it from lat/lon by trigger.

Apply `migrations/0003_polygon_navigation_schema.sql` (idempotent, additive; check it against the deployed schema first).

## 5. SQLite schema (`storage/sqlite_manager.py`)

* `missions`: mission_id PK, device_id, lake_id, status, payload_hash, gcs_latitude/longitude, polygon_json,
  total_waypoints, current_waypoint_index, progress_percent, waypoint_load_ack, created/loaded/started/completed/updated_at,
  notes, cloud_version, cloud_synced_version, waypoints_cloud_synced, last_sync_error
* `mission_waypoints`: (mission_id, sequence_order) PK, latitude, longitude, waypoint_type, status
  (PENDING/ACTIVE/COMPLETED/SKIPPED — same as Supabase), reached_at, cloud_dirty
* `sensor_records`: local_record_id UNIQUE, mission_id, device_id, recorded_at, hardware_timestamp, latitude, longitude,
  heading, gps_valid, gps_age_seconds, ph, tds, turbidity, temperature_c, humidity_percent, sync_status
  (PENDING/SYNCED/FAILED), retry_count, next_attempt_at, last_upload_attempt, last_upload_error, synced_at, created_at
  — indexed on (sync_status, recorded_at). WAL mode.

## 6. API (auth: `Authorization: Bearer <API_AUTH_TOKEN>` or `X-API-Key`)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/missions` | body = mission payload below → `201` ack, `422` validation errors, `409` duplicate/conflict |
| GET | `/api/missions`, `/api/missions/current`, `/api/missions/{id}`, `/api/missions/{id}/waypoints` | status / progress |
| POST | `/api/missions/{id}/start` · `/pause` · `/resume` · `/abort` | `409` wrong state, `412` hardware precondition |
| POST | `/api/emergency-stop` | zero motors immediately, abort current mission |
| GET | `/api/telemetry`, `/api/sensor-records?mission_id=&limit=` | latest frame / local records |
| GET | `/api/health` | no auth |
| WS | `/ws/telemetry?token=<API_AUTH_TOKEN>` | frame every `TELEMETRY_INTERVAL_S`; Origin must be in `CORS_ALLOWED_ORIGINS` |

Mission payload:
```json
{"mission_id":"uuid","device_id":"BOT001","lake_id":null,
 "ground_control":{"latitude":12.91686,"longitude":77.48698},
 "polygon":[{"latitude":12.9169,"longitude":77.487}, "..."],
 "waypoints":[{"sequence_order":0,"latitude":12.91686,"longitude":77.48698,"type":"GCS"},
              {"sequence_order":1,"latitude":12.9169,"longitude":77.48705,"type":"COVERAGE"},
              "...",
              {"sequence_order":N,"latitude":12.91686,"longitude":77.48698,"type":"GCS"}],
 "sweep_spacing_m":5.0}
```
Waypoint types: `GCS` (first/last only), `COVERAGE`, `TRANSIT`.

Ack: `{"ok":true,"mission_id":"…","status":"READY","waypoint_load_ack":true,"stored_waypoints":N,"payload_hash":"…","duplicate":false,"loaded_at":"…"}`

Telemetry frame (WebSocket, MQTT `lakebot/<device>/telemetry`, `GET /api/telemetry`):
```json
{"type":"telemetry","device_id":"BOT001","timestamp":1730800000000,"mission_id":"…","mission_status":"ACTIVE",
 "position":{"latitude":…,"longitude":…,"gps_valid":true,"gps_age_s":0.8},"heading":182.4,"heading_valid":true,
 "navigation":{"nav_state":"NAVIGATING","current_waypoint_index":4,"total_waypoints":12,"completed_waypoints":4,
   "target_waypoint":{"sequence_order":4,"latitude":…,"longitude":…,"type":"COVERAGE"},"distance_to_target_m":7.3,
   "bearing_to_target_deg":91.0,"heading_error_deg":-3.2,"progress_percent":33.3,"returning_to_gcs":false,"hold_reason":null},
 "motors":{"state":"MOVING","commanded":{"left":145,"right":155},"last_sent":{…},"reported":{"left":145,"right":155}},
 "sensors":{"ph":7.1,"tds":214.2,"turbidity":15.3,"temperature_c":27.4,"humidity_percent":71.2,
   "hardware_timestamp":"…","age_s":0.9,"latitude":…,"longitude":…},
 "hardware":{"stm32_port_open":true,"stm32_link_alive":true,"last_packet_age_s":0.9},
 "cloud":{"online":true,"pending_records":0}}
```

## 7. Future grid analytics (not navigation)

Raw readings keep lat/lon, `position_geom` (SRID 4326), timestamps and `mission_id`; the lake polygon is stored as
`missions.polygon_geom` / `lakes.boundary_geom`. Grid cells can later be classified with `ST_Contains` and averaged per
grid (example query at the end of the migration). No grid IDs are needed at capture time.

## 8. Run & deploy

```bash
python3 -m venv /opt/lake-bot/venv
/opt/lake-bot/venv/bin/pip install -r requirements.txt
cd tests && python -m unittest discover -p "test_*.py"     # mocked hardware
python main.py                                              # dev (reads .env)
```

Raspberry Pi (systemd, dedicated `lakebot` user):
```bash
sudo useradd --system --home /opt/lake-bot --groups dialout lakebot
sudo mkdir -p /etc/lake-bot && sudo cp .env.example /etc/lake-bot/lake-bot.env   # then edit
sudo chown root:lakebot /etc/lake-bot/lake-bot.env && sudo chmod 640 /etc/lake-bot/lake-bot.env
sudo cp systemd/lake-bot-autonomous.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable lake-bot-autonomous
sudo systemctl start lake-bot-autonomous
sudo systemctl status lake-bot-autonomous
sudo systemctl restart lake-bot-autonomous
sudo systemctl stop lake-bot-autonomous
journalctl -u lake-bot-autonomous -f
journalctl -u lake-bot-autonomous --since "1 hour ago"
```
Data lives in `/var/lib/lake-bot` (`SQLITE_PATH`, `WAYPOINT_JSON_PATH`). Expose the API to the Vercel dashboard over
HTTPS/WSS (e.g. a reverse proxy or tunnel) and set `API_AUTH_TOKEN` + `CORS_ALLOWED_ORIGINS`.
