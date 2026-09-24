# Final Requirement Verification Checklist

| Requirement | Implemented | File/Location | Notes |
|---|---|---|---|
| STM32 UART reception (single combined packet: motors+gps+compass+sensors) | Yes | `hardware/stm32.py` | line-buffered, handles partial reads |
| Combined JSON packet parsing (robust) | Yes | `hardware/stm32.py::_handle_line` | malformed/whitespace/extra fields handled, never crashes |
| GPS+compass state updated from every STM32 packet (0.5 Hz) | Yes | `hardware/gps.py`, `measurement_manager.py::_process_stm32_packet` | no dedicated GPS serial link; fed by the STM32 stream |
| Continuous GPS+heading telemetry for frontend | Yes | `measurement_manager.py::_publish_position_telemetry` | MQTT `telemetry/position`, published every packet regardless of motor state |
| Motor state derived from `motors.left/right` | Yes | `hardware/motor_controller.py`, `measurement_manager.py::_process_stm32_packet` | no Arduino/USB link; `left==0 AND right==0` -> IDLE, else MOVING |
| Motor state detection (IDLE/MOVING/UNKNOWN) | Yes | `hardware/motor_controller.py::MotorState` | freshness-based; forced UNKNOWN immediately on STM32 disconnect |
| Sensor sampling gated to once per 6s while IDLE (not every 0.5 Hz packet) | Yes | `measurement_manager.py::_process_stm32_packet` (`SENSOR_SAMPLE_INTERVAL_SECONDS`) | resets when motors leave IDLE |
| No readings while motors move | Yes | `measurement/measurement_manager.py::_process` | RULE 1 |
| No readings when motor state unknown | Yes | `measurement/measurement_manager.py::_process` | RULE 2; also forced UNKNOWN on STM32 disconnect |
| GPS validation (valid + fresh) | Yes | `hardware/gps.py::get_fix`, `measurement_manager.py` | age-based validity, `GPS_MAX_AGE_SECONDS`, unchanged |
| 5m configurable grid matching (Haversine) | Yes | `measurement/grid_matcher.py` | `GRID_MATCH_RADIUS_METERS` config, nearest-grid deterministic rule |
| Grid sync from Supabase (never hardcoded) | Yes | `measurement/grid_matcher.py::GridSyncWorker`, `cloud/supabase_client.py::fetch_grids` | cached in SQLite `grid_cache` |
| Measurement sessions | Yes | `measurement/session_manager.py`, `storage/sqlite_manager.py` | ACTIVE/COMPLETED lifecycle |
| MAX_READINGS_PER_GRID global config | Yes | `config/settings.py` | single source of truth |
| Maximum is per-SESSION, not lifetime | Yes | `storage/sqlite_manager.py::increment_sample_count` | new session created after completion |
| Completed session immutability | Yes | `session_manager.py::get_or_create_active_session` | only looks up `status='ACTIVE'` sessions |
| New session on revisit | Yes | `session_manager.py`, tested in `tests/test_acceptance.py::test_session_completes_and_revisit_creates_new_session` | |
| Sample numbering 1..MAX per session | Yes | `measurement_manager.py::_process`, `UNIQUE(session_id, sample_number)` | |
| Invalid sensor values -> SQL NULL | Yes | `measurement/sensor_validator.py` | never 0/-1/9999/"NA" |
| NULL excluded from averages | Yes | `storage/average_manager.py::compute_averages` | all-NULL -> average NULL |
| Local SQLite average | Yes | `storage/sqlite_manager.py::upsert_local_average` | keyed on (grid_id, session_id) |
| Averages NOT uploaded to cloud | Yes | `cloud/supabase_client.py`, `cloud/uploader.py` | only `upsert_readings_batch`/`upsert_session` used, no average fields sent |
| Raw readings uploaded to Supabase | Yes | `cloud/uploader.py::_complete_session_in_cloud` | one batched JSON packet per session |
| Offline buffering | Yes | `storage/sqlite_manager.py` (`local_readings`), `storage/buffer_manager.py` | |
| Automatic retry | Yes | `cloud/uploader.py` | unlimited by default (`UPLOAD_MAX_RETRIES=0`) |
| Cloud completion confirmed before marking COMPLETED/cloud_synced | Yes | `cloud/uploader.py::_complete_session_in_cloud` | verifies `count_confirmed_samples(session_id) == MAX_READINGS_PER_GRID` against Supabase before marking completed and before deleting local buffer |
| Buffer cleanup only after confirmed cloud completion | Yes | `cloud/uploader.py::_complete_session_in_cloud` -> `db.delete_session_readings` | only after the count above matches; never on a per-reading upload success |
| Idempotent cloud writes | Yes | `cloud/supabase_client.py::upsert_readings_batch` (`on_conflict="session_id,sample_number"`) | tested in `test_motor_and_uploader.py` |
| Network failure recovery | Yes | `cloud/uploader.py` | decoupled thread, retries on interval |
| SQLite persistence / restart recovery | Yes | `storage/sqlite_manager.py` | WAL mode, durable schema |
| MQTT (centralized config, reconnecting) | Yes | `communication/mqtt_client.py`, `config/settings.py` | all MQTT_* vars centralized |
| systemd unit | Yes | `systemd/lake-bot-backend.service` | Restart=always |
| Automatic boot | Yes | systemd `WantedBy=multi-user.target` | |
| No SSH required for normal operation | Yes | systemd auto-start | |
| Logging | Yes | `monitoring/logger.py` | stdout -> journald; debug motor text gated |
| Health monitoring | Yes | `monitoring/health.py`, published via MQTT in `main.py` | |
| Restart recovery | Yes | SQLite durability + systemd `Restart=always` | |
| Tests | Yes | `tests/` | unit + acceptance + uploader/motor + STM32-integration tests |
| Documentation | Yes | `README.md`, this file | |

## Acceptance-test mapping (spec section 50)

| Test | Status | Location |
|---|---|---|
| TEST1 (motor moving) | Covered | `test_acceptance.py::test_motor_moving_rejects` |
| TEST2 (invalid GPS) | Covered | `test_acceptance.py::test_invalid_gps_rejects` |
| TEST3 (20m outside grid) | Covered | `test_acceptance.py::test_gps_outside_radius_rejects` |
| TEST4 (3m inside grid) | Covered | `test_acceptance.py::test_gps_within_radius_accepts` |
| TEST5 (10/10 completes) | Covered | `test_acceptance.py::test_session_completes_and_revisit_creates_new_session` |
| TEST6 (revisit -> new session) | Covered | same test as above |
| TEST7 (partial invalid field) | Covered | `test_acceptance.py::test_partial_invalid_packet_still_accepted_with_nulls` |
| TEST8 (all-NULL average) | Covered | `test_units.py::test_average_all_null_is_null` |
| TEST9 (offline buffering) | Covered | `test_motor_and_uploader.py::test_offline_buffering_and_idempotent_retry` |
| TEST10 (auto retry on reconnect) | Covered | same test as above |
| TEST11 (idempotent retry, no dup) | Covered | same test as above |
| TEST12 (reboot -> systemd autostart) | **Requires physical hardware** | see README section 14 |
| TEST13 (STM32 disconnected -> motor state UNKNOWN) | Covered | `test_motor_and_uploader.py::test_motor_forced_unknown_on_disconnect`, `test_stm32_integration.py::test_stm32_disconnect_forces_motor_unknown` |
| TEST14 (STM32 disconnect/reconnect) | Partially covered by design (`hardware/stm32.py` reconnect loop); full **hardware test required** | |
| TEST15 (GPS disconnected/stale) | Covered by design (age-based invalidation in `hardware/gps.py`); full **hardware test required** | |
