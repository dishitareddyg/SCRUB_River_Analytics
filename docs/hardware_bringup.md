# Hardware Bring-Up Checklist

Step-by-step guide for bringing up the SCRUB v4 boat on real hardware.

## 1. Wiring Checklist — Dual-Board Topology

The SCRUB v4 uses **two separate Arduino Unos**, each handling a distinct subsystem:

### Board 1: Sensor+GPS Arduino (read-only, GPIO UART)

| Component | Arduino Pin | Notes |
|-----------|-------------|-------|
| GPS module (TX) | Serial RX (pin 0 or SoftwareSerial) | NEO-M8N NMEA @ 9600 baud |
| GPS module (RX) | Serial TX | For configuration if needed |
| Compass (I2C SDA) | A4 | QMC5883L / HMC5883L (onboard NEO-M8N) |
| Compass (I2C SCL) | A5 | |
| Sensor array (pH, TDS, Turbidity, etc.) | Analog pins A0-A3 | One analog pin per sensor |
| DHT11/22 (temp+humidity) | Digital pin 4 | One-wire protocol |
| MQ-135 (gas) | Analog pin A5 | |

**Connected to Pi via**: GPIO hardware UART `/dev/ttyAMA0` at 115200 baud.

### Board 2: Motor+RC Arduino (read+write, USB)

| Component | Arduino Pin | Notes |
|-----------|-------------|-------|
| TB6600 Motor Driver LEFT (PWM) | Digital pin 5 | PWM motor control |
| TB6600 Motor Driver RIGHT (PWM) | Digital pin 6 | PWM motor control |
| Motor Driver DIR L1 | Digital pin 7 | Direction control |
| Motor Driver DIR L2 | Digital pin 8 | Direction control |
| Motor Driver DIR R1 | Digital pin 9 | Direction control |
| Motor Driver DIR R2 | Digital pin 10 | Direction control |
| Motor Driver ENA | 5V or PWM | Enable pin |
| RC Receiver CH1 (steering) | Digital pin 2 | PWM input from FlySky |
| RC Receiver CH2 (throttle) | Digital pin 3 | PWM input from FlySky |
| RC Receiver AUX (MANUAL/AUTO) | Digital pin 12 | Physical switch |
| RC Receiver VCC | 5V | Power from RC receiver |
| RC Receiver GND | GND | Common ground |

**Connected to Pi via**: USB cable (device path configurable, e.g. `/dev/ttyACM0`).

### Raspberry Pi 5 connections

| Component | Pi Connection | Notes |
|-----------|---------------|-------|
| Sensor+GPS Arduino | GPIO 14 (TXD) / GPIO 15 (RXD) | UART @ 115200 baud |
| Motor+RC Arduino | USB port | Device path varies by enumeration |
| Pi GND | Both Arduinos GND | **Common ground is mandatory** |
| Pi 5V | External supply only | Do NOT power Pi from Arduino |
| Pi power | USB-C 5V/3A | Official Pi 5 power supply |

**CRITICAL**: Always connect GND between Pi and both Arduinos before connecting TX/RX or USB.

### Stable USB device path (udev rule)

The USB device path (`/dev/ttyACM0`) can change between reboots depending on enumeration order. To ensure the motor+RC board always appears at the same path, create a udev rule based on the board's serial number:

```bash
# 1. Find the serial number of your motor+RC Arduino
ls -la /dev/serial/by-id/
# Example output: usb-Arduino__www.arduino.cc__Arduino_Uno_Relay_95635323430351B061C0-if00 -> ../../ttyACM0

# 2. Create a udev rule (replace SERIAL with your board's serial number)
sudo nano /etc/udev/rules.d/99-scrub-motor-rc.rules
# Add this line:
SUBSYSTEM=="tty", ATTRS{serial}=="YOUR_SERIAL_NUMBER", SYMLINK+="scrub-motor-rc"

# 3. Reload and apply
sudo udevadm control --reload-rules
sudo udevadm trigger

# 4. Verify
ls -la /dev/scrub-motor-rc
```

Then update `config.yaml`:
```yaml
motor_rc_link:
  device: "/dev/scrub-motor-rc"   # stable udev symlink
```

**Why this matters**: Sending motor commands to the wrong serial port will silently do nothing — the sensor+GPS board will receive motor commands it doesn't understand, and the motor+RC board will never receive them.

## 2. Switching from Simulate to Real Hardware

### Method A: CLI flag (recommended)

```bash
# Simulate (bench test)
python -m nav_service.main --config nav_service/config.yaml --simulate

# Real hardware (no --simulate flag)
python -m nav_service.main --config nav_service/config.yaml
```

### Method B: Config change

In `config.yaml`, the dual-board configuration controls both Arduinos:

```yaml
sensor_gps_link:
  device: "/dev/ttyAMA0"         # Pi GPIO UART
  baud: 115200
  staleness_timeout_s: 3.0       # seconds before sensor board considered stale

motor_rc_link:
  device: "/dev/ttyACM0"         # USB (or use udev symlink)
  baud: 115200
  staleness_timeout_s: 1.0       # seconds before motor board considered stale
```

To fall back to legacy single-board mode, use the old `arduino_link:` key instead.

### Enable UART on Pi 5

```bash
sudo raspi-config
# Interface Options → Serial Port
# Login shell over serial: NO
# Serial port hardware enabled: YES
sudo reboot
```

Verify UART is available:
```bash
ls -la /dev/ttyAMA0
ls -la /dev/serial0
```

## 3. Verify UART Links are Alive

### Check health endpoint

```bash
curl http://localhost:8000/api/health
```

Response should show:
```json
{"status": "ok", "arduino_link": "connected", "uptime_s": <number>}
```

If either Arduino is not responding, the health endpoint still returns "ok" but you may see read errors in the logs. The system will report stale data with appropriate fail-safes (gps_fix=0 for sensor board, mode=MANUAL for motor board).

### Check telemetry stream

Connect to WebSocket and verify data is flowing:
```bash
# Using websocat (install via: cargo install websocat)
websocat ws://localhost:8000/ws
```

You should see JSON telemetry messages at ~3 Hz with non-zero GPS coordinates and sensor values.

### Check serial directly

```bash
# Monitor sensor+GPS Arduino output
screen /dev/ttyAMA0 115200
# or
minicom -D /dev/ttyAMA0 -b 115200

# Monitor motor+RC Arduino output
screen /dev/ttyACM0 115200
# or use udev symlink if configured:
screen /dev/scrub-motor-rc 115200
```

Sensor+GPS board should output JSON like:
```json
{"seq":1234,"gps":{"lat":12.916,"lon":77.486},"hdg":187.5,"sensors":{"ph":7.2,"tds":350,...}}
```

Motor+RC board should output JSON like:
```json
{"seq":5678,"mode":"AUTO","rc":{"ch1":1500,"ch2":1500}}
```

## 4. Safety Notes

### Physical RC switch is the ultimate override

The RC receiver's physical switch is wired directly to the Arduino. This is the **only** guaranteed fail-safe. The Pi's software override (`set_manual` command) is additive but cannot override a physical MANUAL switch.

**Before first water launch:**
1. Put the physical RC switch in MANUAL position.
2. Verify motors respond to RC stick inputs.
3. Verify the dashboard shows `effective_mode: "MANUAL"` and `RC MANUAL` badge.
4. Toggle the dashboard manual override ON — mode should still be MANUAL.
5. Toggle the dashboard manual override OFF — mode should still be MANUAL (physical switch wins).
6. Switch the physical RC switch to AUTO — verify mode becomes AUTO.

### Emergency stop test

1. With boat out of water (or in safe area), start a mission.
2. Click **E-Stop** on the dashboard.
3. Verify motors stop immediately (left_power=0, right_power=0).
4. State should show `STOPPED`.

### Pre-launch checklist

- [ ] Physical RC switch tested in both positions
- [ ] Emergency stop tested and verified
- [ ] GPS fix acquired (satellites > 4, fix_quality > 0)
- [ ] Geofence configured (`gcs_lat`, `gcs_lon` in config.yaml)
- [ ] Battery voltage sufficient (> 11V for 2S LiPo)
- [ ] All sensors submerged and reading plausible values
- [ ] Boat tested in controlled environment (pool/pond) before lake deployment

## 5. Firebase Setup

### Disable for bench testing

In `config.yaml`:
```yaml
firebase:
  enabled: false
```

This completely bypasses Firebase — no SDK import, no credential check, no network calls.

### Enable for production

1. Create a Firebase project at https://console.firebase.google.com/
2. Generate a service account key:
   - Project Settings → Service Accounts → Generate New Private Key
   - Save as `nav_service/firebase-service-account.json`
3. Update `config.yaml`:
```yaml
firebase:
  enabled: true
  credentials_path: "firebase-service-account.json"
  database_url: "https://scrub-v4-default-rtdb.asia-southeast1.firebasedatabase.app/"
  live_path: "live_telemetry"
  missions_path: "missions"
  live_push_hz: 1.0
```

### Verify Firebase connection

With Firebase enabled, the backend logs should show:
```
Firebase Realtime Database initialized
```

If credentials are missing or invalid:
```
Firebase credentials not found: firebase-service-account.json — continuing without Firebase
```

The system continues operating with local SQLite only — Firebase is purely additive.

### Firebase RTDB data structure

```
live_telemetry/              ← single node, overwritten at ~1 Hz
  { telemetry payload }

missions/
  {mission_id}/
    waypoints/
      {waypoint_index}/
        { lat, lon, avg_sensors, sample_count }
```
