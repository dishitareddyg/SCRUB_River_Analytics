# Lake Analysis Bot — Raspberry Pi 5 Backend

Software-to-hardware bridge for a manually operated lake-water-analysis
bot. All sensors, the NEO-M8N GPS/compass, motors, and the RC controller
are wired to an STM32, which relays one combined UART packet per cycle
to the Raspberry Pi 5 backend, which in turn talks to MQTT, local
SQLite, and Supabase.

---

## 1. Architecture

```
   Sensors (pH/TDS/Turb/DHT11)  --\
   NEO-M8N GPS/compass          ---+--> STM32 --UART--> +-------------------+
   Motors + RC controller       --/                     |                   |
                                                          | Raspberry Pi 5    |----MQTT----> Broker
                                                          | Backend (Python)  |
                                                          |                   |----HTTPS---> Supabase
                                                          +-------------------+
                                                                   |
                                                                SQLite
                                                         (offline buffer, sessions,
                                                          local averages, grid cache)
```

The STM32 is the **sole hardware input** to the RPi 5: it sends one
combined JSON packet over UART at 0.5 Hz (every ~2s):

```json
{
  "device_id": "BOT001",
  "timestamp": "...",
  "motors": {"left": 0, "right": 0},
  "gps": {"latitude": 12.123456, "longitude": 77.123456},
  "compass": {"heading": 182.4},
  "sensors": {"ph": 7.12, "tds": 214.2, "turbidity": 15.3,
              "temperature_c": 27.4, "humidity_percent": 71.2}
}
```

Pipeline for every STM32 packet (see `measurement/measurement_manager.py::on_stm32_packet`):

```
Receive & parse (hardware/stm32.py)
        |
Update GPS + compass state from gps/compass; publish current
position+heading to MQTT telemetry continuously (every packet, 0.5 Hz,
for real-time frontend visualization) -- independent of motor state
        |
Update motor state from motors.left/right
  left==0 AND right==0 -> IDLE, otherwise -> MOVING
  stale/missing STM32 link -> UNKNOWN
        |
If MOVING or UNKNOWN: no sensor acquisition (safety rule) -- STOP HERE
        |
If IDLE: sample-cadence gate -- only once every
SENSOR_SAMPLE_INTERVAL_SECONDS (default 6s), NOT on every 0.5 Hz packet,
does the packet's `sensors` object enter the acceptance pipeline below
        |
Motor state check (IDLE required, re-checked)  --MOVING/UNKNOWN--> REJECT
        |
GPS validity + freshness check     --invalid/stale--->  REJECT
        |
Grid matching (Haversine, radius)  --outside radius-->  REJECT
        |
Sensor field validation (bad field -> NULL, not rejection)
        |
Session lookup/creation (reuse ACTIVE, never touch COMPLETED)
        |
ONE atomic SQLite transaction (record_accepted_sample):
  - insert raw reading into the TEMPORARY upload buffer (local_readings)
  - update running sum/count aggregation on the session
  - increment sample_count
  - if this was the final sample: mark session COMPLETED and persist
    the final LOCAL average (local_averages, never uploaded)
        |
(independently, in the background) cloud/uploader.py drains the buffer.
For an in-progress session it only refreshes the session's own metadata
row in Supabase (never a completion marker). Once a session is locally
COMPLETED, its pending raw samples are sent as ONE batched JSON packet,
Supabase is queried to CONFIRM every required sample is actually
persisted there, and ONLY THEN is the session marked COMPLETED/
cloud_synced in Supabase and its temporary raw samples permanently
DELETED from local_readings (SQLite never keeps raw readings once cloud
completion has been confirmed -- see "Cloud upload behavior" below)
```

### Project layout

```
lake-bot-backend/
├── config/settings.py            # single source of truth for ALL configuration
├── hardware/
│   ├── stm32.py                  # STM32 UART combined-packet reader thread (sole hardware input)
│   ├── gps.py                    # GPS/compass state, fed by the STM32 stream (no own serial link)
│   └── motor_controller.py       # motor state, fed by the STM32 stream (no own serial link)
├── communication/mqtt_client.py  # MQTT pub client, auto-reconnect
├── measurement/
│   ├── grid_matcher.py           # Haversine matching + grid sync from Supabase
│   ├── sensor_validator.py       # field validation -> NULL on bad values
│   ├── session_manager.py        # session lifecycle (active/completed/new)
│   └── measurement_manager.py    # THE acceptance pipeline (business rules)
├── storage/
│   ├── sqlite_manager.py         # schema + all local persistence
│   ├── buffer_manager.py         # thin wrapper over the upload queue
│   └── average_manager.py        # NULL-aware local averages
├── cloud/
│   ├── supabase_client.py        # Supabase access (grids, sessions, readings)
│   └── uploader.py               # background offline-buffer drain worker
├── monitoring/
│   ├── logger.py                 # stdout logging (captured by journald)
│   └── health.py                 # in-memory health snapshot
├── main.py                       # wires everything together, run this
├── requirements.txt
├── .env.example                  # copy to .env and fill in
├── systemd/lake-bot-backend.service
├── migrations/0001_reference_schema.sql   # reference only; schema already exists
├── obsolete_hardware/             # PREVIOUS architecture's Arduino firmware; unused, kept for reference
└── tests/                        # pytest unit + acceptance tests
```

---

## 2. Hardware connections

| Device | Interface | Notes |
|---|---|---|
| STM32 (sensors + NEO-M8N GPS/compass + motors + RC controller) | UART, 5V logic via level shifter if needed | sends one combined JSON packet at 0.5 Hz (~every 2s) |
| Raspberry Pi 5 | UART from STM32 only | this is the **sole** hardware input to the backend |

All sensors, the GPS/compass module, the motors, and the RC controller
are wired to the STM32 — none of them connect to the Raspberry Pi
directly. Use a stable device path (`/dev/serial/by-id/...`) for the
STM32 UART link where possible, since `/dev/ttyAMA*`/`/dev/ttyUSB0`-style
names can shift across reboots. Run `ls -l /dev/serial/by-id/` on the Pi
to find the correct path and put it in `.env` as `STM32_SERIAL_PORT`.

---

## 3. Software requirements

- Raspberry Pi OS (Bookworm or later), Raspberry Pi 5
- Python 3.11+
- A running MQTT broker (e.g. Mosquitto) reachable from the Pi
- A Supabase project with the schema described in the project spec
  (see `migrations/0001_reference_schema.sql` for reference)

---

## 4. Installation

```bash
# On the Raspberry Pi
sudo apt update
sudo apt install -y python3-venv python3-pip

git clone <your-repo-url> /home/pi/lake-bot-backend
cd /home/pi/lake-bot-backend

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
nano .env   # fill in real values (see section 5)

# make sure the pi user can access serial ports
sudo usermod -aG dialout pi
sudo usermod -aG tty pi
# log out/in (or reboot) for group changes to take effect
```

---

## 5. Configuration (environment variables)

All configuration lives in `config/settings.py`, loaded from `.env`.
See `.env.example` for the full list with defaults. Key groups:

- **Measurement rules**: `MAX_READINGS_PER_GRID`, `GRID_MATCH_RADIUS_METERS`
- **Timing**: `GPS_UPDATE_INTERVAL_SECONDS`, `SENSOR_PACKET_INTERVAL_SECONDS`
  (STM32 packet cadence, ~2s), `SENSOR_SAMPLE_INTERVAL_SECONDS` (sensor
  sampling cadence while IDLE, default 6s), `GPS_MAX_AGE_SECONDS`,
  `MOTOR_STATE_MAX_AGE_SECONDS`
- **Serial**: `STM32_SERIAL_PORT`, `STM32_BAUDRATE`, `STM32_SERIAL_TIMEOUT`
  — the only serial link; GPS/motors no longer have their own port
- **MQTT**: `MQTT_BROKER_HOST`, `MQTT_BROKER_PORT`, `MQTT_USERNAME`,
  `MQTT_PASSWORD`, `MQTT_CLIENT_ID`, `MQTT_KEEPALIVE`, `MQTT_QOS`,
  `MQTT_RETAIN`, `MQTT_RECONNECT_DELAY`, `MQTT_BASE_TOPIC`
- **Supabase**: `SUPABASE_URL`, `SUPABASE_KEY` — never commit real values
- **Validation ranges**: `PH_MIN/MAX`, `TDS_MIN/MAX`, `TURBIDITY_MIN/MAX`,
  `TEMPERATURE_MIN/MAX`, `HUMIDITY_MIN/MAX`
- **SQLite**: `SQLITE_PATH`
- **Logging**: `LOG_LEVEL`

Never hardcode secrets in source code. `.env` is git-ignored; only
`.env.example` (with placeholders) is committed.

### MQTT topics published

| Topic | When |
|---|---|
| `lakebot/<device_id>/health` | every `HEALTH_PUBLISH_INTERVAL_SECONDS` |
| `lakebot/<device_id>/telemetry/position` | every STM32 packet (0.5 Hz) — current GPS lat/lon, heading, validity, for real-time frontend visualization |
| `lakebot/<device_id>/sensor/accepted` | a sample is accepted |
| `lakebot/<device_id>/sensor/rejected` | a sample is rejected (with reason) |
| `lakebot/<device_id>/session/completed` | a session reaches `MAX_READINGS_PER_GRID` |

The backend does not subscribe to any command topics — there is
intentionally no dashboard/MQTT motor control (spec RULE 18).

---

## 6. Running manually (development)

```bash
source venv/bin/activate
python main.py
```

Logs print to stdout. Press `Ctrl+C` for graceful shutdown.

Run tests:

```bash
pip install pytest
pytest tests/ -v
```

---

## 7. Installing the systemd service (production)

```bash
sudo cp systemd/lake-bot-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable lake-bot-backend
sudo systemctl start lake-bot-backend
```

After this, **rebooting the Raspberry Pi automatically starts the
backend** — no SSH or manual `python main.py` is required for normal
operation. Adjust `User`, `WorkingDirectory`, `EnvironmentFile`, and
`ExecStart` paths in the unit file if your install path differs from
`/home/pi/lake-bot-backend`.

### Managing the service

```bash
sudo systemctl status lake-bot-backend
sudo systemctl restart lake-bot-backend
sudo systemctl stop lake-bot-backend
```

### Checking logs

```bash
journalctl -u lake-bot-backend -f          # follow live
journalctl -u lake-bot-backend --since today
```

---

## 8. Measurement / session lifecycle

- A grid can have many sessions over time, but only **one ACTIVE session
  at a time**.
- Every accepted sample for a grid goes into its current ACTIVE session
  until `sample_count == MAX_READINGS_PER_GRID`, at which point the
  session becomes **COMPLETED and immutable**.
- The **next** accepted sample for that grid (whenever it occurs) creates
  a **new session** with a new UUID and sample numbering restarting at 1.
  GPS jitter around the radius boundary cannot fragment one visit into
  multiple sessions, because a session is only replaced once it is
  actually COMPLETED — not merely because GPS briefly left the radius.
- Local averages are computed once per completed session and are
  **local-only** (SQLite `local_averages` table) — never uploaded to
  Supabase.

## 9. Cloud upload behavior

- Sensor acquisition and cloud upload are fully decoupled
  (`cloud/uploader.py` runs independently on its own thread/poll loop).
- Every accepted reading is written to SQLite (`local_readings`) in the
  **same transaction** as the session update, so an accepted reading can
  never exist without also being buffered for upload.
- A session's raw samples are batched into **one JSON packet** per
  session (`{"session_id", "grid_id", "device_id", "samples": [...]}`,
  up to `MAX_READINGS_PER_GRID` entries) rather than uploaded one
  request per sample. Supabase still stores each sample as its own
  `sensor_readings` row — the packet is transport format only.
- **Cloud completion gate (critical):** once a session has collected
  all its samples locally (`status='COMPLETED'`), the uploader (a)
  uploads its pending batched packet, (b) asks Supabase directly how
  many of that session's samples are actually confirmed persisted
  (`count_confirmed_samples`), and — **only if that count equals
  `MAX_READINGS_PER_GRID`** — (c) marks the session `COMPLETED`/
  `cloud_synced` in Supabase and (d) permanently deletes the session's
  temporary raw samples from `local_readings`. If the upload or the
  verification fails or under-counts, none of (c)/(d) happens: the
  temporary data is retained in full and the whole session is retried
  on the next cycle. A session is therefore never marked
  completed/synced in Supabase based on a successful upload *call*
  alone — only on a confirmed count.
- The uploader retries indefinitely by default (`UPLOAD_MAX_RETRIES=0`).
- Uploads use `upsert` keyed on the existing `UNIQUE(session_id,
  sample_number)` constraint, so retrying the same (or a partially
  applied) batch after a lost response never creates duplicate rows.
- An in-progress (`ACTIVE`) session's row is registered/refreshed in
  Supabase as soon as it changes locally (`completed_at` stays `NULL`)
  — this is metadata only and is never a completion marker, so it is
  always safe to push regardless of how many of its samples are
  uploaded yet.

---

## 10. Failure recovery

| Failure | Behavior |
|---|---|
| STM32 disconnected | Backend stays alive, reconnects automatically, logs a warning; motor state is forced to `UNKNOWN` immediately (never assumed idle), and GPS/motor state also naturally go stale/`UNKNOWN` after `GPS_MAX_AGE_SECONDS`/`MOTOR_STATE_MAX_AGE_SECONDS` if packets stop arriving |
| GPS/compass data missing or stale in the STM32 packet | `gps_fix_valid` becomes false after `GPS_MAX_AGE_SECONDS` with no fresh fix; no samples accepted |
| Malformed/invalid `motors` object in a packet | Motor state is left untouched for that packet (not guessed), so freshness-based staleness still applies |
| MQTT broker unreachable | Publishes are no-ops with a warning logged; hardware acquisition unaffected |
| Supabase/internet unreachable | Accepted readings buffer in SQLite; uploader retries automatically once connectivity returns |
| Process/Pi restart | SQLite (WAL mode) preserves session state, buffered readings, and averages; systemd restarts the process automatically |

---

## 11. Testing

`tests/test_units.py` — sensor validation, Haversine distance, NULL-aware
averages.

`tests/test_acceptance.py` — end-to-end pipeline tests matching the
spec's acceptance matrix (motor-moving rejection, invalid/stale GPS
rejection, outside-radius rejection, in-radius acceptance, session
completion + revisit-creates-new-session, partial-invalid-packet
handling).

`tests/test_motor_and_uploader.py` — motor state derivation from
`left`/`right` (idle/moving/unknown-on-silence/unknown-on-forced-disconnect),
offline buffering, automatic retry, and idempotent retry (no duplicate
uploads).

`tests/test_stm32_integration.py` — the new combined-packet pipeline:
GPS+compass state updates and continuous telemetry publishing, motor
state derived from `motors.left/right`, the 6-second sensor-sampling
cadence while IDLE, and STM32-packet-level parsing/robustness.

```bash
pytest tests/ -v
```

Tests that require **physical hardware** (real GPS fix acquisition,
real STM32 serial traffic, a real Supabase project, a real MQTT broker,
and a full power-cycle reboot test) are not simulated here and must be
verified on the actual bot — see section 12 below.

---

## 12. Hardware architecture note

The backend assumes all sensors, the NEO-M8N GPS/compass, motors, and
the RC controller are wired to the STM32, and that the STM32 relays one
combined JSON packet per cycle (0.5 Hz) over a single UART link to the
Raspberry Pi 5 (see section 1 for the packet shape). There is no
Arduino and no separate GPS/motor serial link in this architecture; the
previous Arduino-based motor-monitoring firmware is kept only for
historical reference under `obsolete_hardware/` and is not used by this
backend.

---

## 13. Assumptions

- `MAX_READINGS_PER_GRID` defaults to 10 and `GRID_MATCH_RADIUS_METERS`
  defaults to 5.0, matching the spec's examples; both are fully
  configurable via `.env`.
- Sensor validation ranges (pH 0–14, TDS 0–5000 ppm, turbidity 0–3000 NTU,
  temperature −10–60 °C, humidity 0–100%) are reasonable generic bounds
  for these sensor types since the spec did not supply project-specific
  limits; adjust in `.env` if your project has documented limits.
- The STM32 sends its combined packet at 0.5 Hz (every ~2s); sensor
  *sampling* (persisted readings) intentionally happens at a slower,
  configurable cadence (`SENSOR_SAMPLE_INTERVAL_SECONDS`, default 6s)
  while motors are IDLE, rather than on every packet.
- `GPS_MAX_AGE_SECONDS` (6s) and `MOTOR_STATE_MAX_AGE_SECONDS` (3s)
  tolerate a small number of missed STM32 packets before GPS/motor
  state are considered stale/`UNKNOWN`; tune these if the STM32's
  actual packet cadence differs from 0.5 Hz.
- Supabase's `measurement_sessions`/`sensor_readings` tables already
  exist with the schema shown in the spec, including
  `UNIQUE(session_id, sample_number)` — this is what makes upload
  idempotency possible without any schema changes.
- The STM32 is reachable at a stable `/dev/serial/by-id/...` (or
  `/dev/ttyAMA*`) path once configured; the exact path must be captured
  on the actual Pi hardware.

## 14. Items that require physical hardware testing

- Actual GPS fix acquisition/accuracy indoors vs outdoors, and real
  antenna/compass behavior of the NEO-M8N module as relayed by the STM32.
- Real serial framing/timing of the STM32's combined packet over the
  actual UART cabling/level shifters used.
- End-to-end verification against the real Supabase project (RLS
  policies, network latency, real credentials).
- A full power-cycle reboot test on the physical Raspberry Pi 5 to
  confirm systemd auto-start and SQLite/WAL recovery under real power
  conditions.
- Confirming the STM32 firmware's actual packet rate/timing matches the
  configured `SENSOR_PACKET_INTERVAL_SECONDS`/freshness settings.
