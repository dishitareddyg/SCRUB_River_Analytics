#!/usr/bin/env python3
"""
main.py

Entrypoint for the Lake Analysis Bot backend.

Run manually for development:
    python main.py

Run in production via systemd (see systemd/lake-bot-backend.service):
    sudo systemctl start lake-bot-backend

Startup order:
    1. Logging
    2. SQLite (schema init / recovery)
    3. Supabase client
    4. MQTT client
    5. Health monitor
    6. Grid sync worker (background)
    7. GPS + compass state (in-memory, fed by the STM32 stream)
    8. Motor state (in-memory, fed by the STM32 stream)
    9. Measurement manager (pipeline glue)
    10. STM32 UART worker (background) -- the SOLE hardware input. All
        sensors, the NEO-M8N GPS/compass, motors and the RC controller
        are wired to the STM32, which relays one combined JSON packet
        per cycle (motors + gps + compass + sensors) over this link,
        driving GPS/compass telemetry, motor state, and (once IDLE)
        gated sensor sampling.
    11. Cloud uploader worker (background)
    12. Main loop: periodic health publish + graceful shutdown handling
"""

from __future__ import annotations

import signal
import sys
import time

from cloud.supabase_client import SupabaseClientWrapper
from cloud.uploader import UploaderWorker
from communication.mqtt_client import MQTTClient
from config.settings import settings
from hardware.gps import GPSWorker
from hardware.motor_controller import MotorControllerWorker
from hardware.stm32 import STM32Worker
from measurement.grid_matcher import GridMatcher, GridSyncWorker
from measurement.measurement_manager import MeasurementManager
from measurement.sensor_validator import SensorValidator
from measurement.session_manager import SessionManager
from monitoring.health import HealthMonitor
from monitoring.logger import get_logger
from storage.sqlite_manager import SQLiteManager

logger = get_logger(__name__)


class Application:
    def __init__(self):
        self.health = HealthMonitor()
        self.db = SQLiteManager()
        self.supabase = SupabaseClientWrapper()
        self.mqtt = MQTTClient(health=self.health)

        self.grid_matcher = GridMatcher(self.db)
        self.grid_sync = GridSyncWorker(self.db, self.supabase)

        self.gps = GPSWorker(health=self.health)
        self.motor = MotorControllerWorker(health=self.health)

        self.session_manager = SessionManager(self.db)
        self.sensor_validator = SensorValidator()

        self.measurement_manager = MeasurementManager(
            sqlite_manager=self.db,
            gps_worker=self.gps,
            motor_worker=self.motor,
            grid_matcher=self.grid_matcher,
            session_manager=self.session_manager,
            sensor_validator=self.sensor_validator,
            mqtt_client=self.mqtt,
            health=self.health,
        )

        self.stm32 = STM32Worker(
            on_packet=self.measurement_manager.on_stm32_packet,
            health=self.health,
            on_disconnect=self.motor.force_unknown,
        )
        self.uploader = UploaderWorker(self.db, self.supabase, health=self.health)

        self._stop_event = None  # set in run()

    def start(self) -> None:
        logger.info("Starting Lake Analysis Bot backend (device_id=%s)", settings.DEVICE_ID)
        self.mqtt.start()
        self.grid_sync.start()
        self.gps.start()
        self.motor.start()
        self.stm32.start()
        self.uploader.start()
        logger.info("All subsystems started")

    def stop(self) -> None:
        logger.info("Shutting down...")
        for name, worker in [
            ("stm32", self.stm32),
            ("motor", self.motor),
            ("gps", self.gps),
            ("grid_sync", self.grid_sync),
            ("uploader", self.uploader),
        ]:
            try:
                worker.stop()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error stopping %s: %s", name, exc)
        try:
            self.mqtt.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        logger.info("Shutdown complete")

    def run_forever(self) -> None:
        import threading
        self._stop_event = threading.Event()

        def _handle_signal(signum, _frame):
            logger.info("Received signal %s, stopping", signum)
            self._stop_event.set()

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        self.start()
        try:
            while not self._stop_event.is_set():
                snapshot = self.health.snapshot()
                self.mqtt.publish("health", snapshot)
                self._stop_event.wait(settings.HEALTH_PUBLISH_INTERVAL_SECONDS)
        finally:
            self.stop()


def main() -> int:
    app = Application()
    app.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
