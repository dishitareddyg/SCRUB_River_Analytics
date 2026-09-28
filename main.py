#!/usr/bin/env python3
"""
main.py

Entrypoint for the Autonomous Navigation & Lake Analysis Bot backend.

Startup Order:
  1. Logging setup
  2. Health Monitor & SQLite initialization
  3. Supabase client & MQTT client
  4. Grid matcher & GridSyncWorker
  5. GPSWorker & MotorControllerWorker
  6. Navigator (autonomous movement state machine)
  7. MeasurementManager (sensor gating, grid session manager, acceptance pipeline)
  8. MissionManager (Supabase mission fetcher & waypoint feeder)
  9. STM32Worker (bidirectional UART: reads combined packets, shares serial port with motor controller)
  10. Cloud UploaderWorker (verified sync to Supabase)
  11. Main loop: health telemetry broadcast & graceful shutdown
"""

from __future__ import annotations

import signal
import sys
import threading
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
from navigation.mission_manager import MissionManager
from navigation.navigator import Navigator
from storage.sqlite_manager import SQLiteManager

logger = get_logger(__name__)


class Application:
    def __init__(self):
        logger.info("Initializing Autonomous Navigation Bot (device_id=%s)", settings.DEVICE_ID)

        self.health = HealthMonitor()
        self.db = SQLiteManager()
        self.supabase = SupabaseClientWrapper()
        self.mqtt = MQTTClient(health=self.health)

        self.grid_matcher = GridMatcher(self.db)
        self.grid_sync = GridSyncWorker(self.db, self.supabase)

        self.gps = GPSWorker(health=self.health)
        self.motor = MotorControllerWorker(health=self.health)

        # Navigator handles steering & waypoint arrival
        self.navigator = Navigator(
            gps=self.gps,
            motor=self.motor,
            health=self.health,
            on_grid_arrived=None,  # wired below after measurement_manager is created
        )

        self.session_manager = SessionManager(self.db)
        self.sensor_validator = SensorValidator()

        # MeasurementManager coordinates sensor acquisition when arrived at grid
        self.measurement_manager = MeasurementManager(
            sqlite_manager=self.db,
            gps_worker=self.gps,
            motor_worker=self.motor,
            grid_matcher=self.grid_matcher,
            session_manager=self.session_manager,
            sensor_validator=self.sensor_validator,
            navigator=self.navigator,
            mission_manager=None,  # wired below
            mqtt_client=self.mqtt,
            health=self.health,
        )

        # Wire Navigator arrival callback to MeasurementManager
        self.navigator._on_grid_arrived = self.measurement_manager.on_grid_arrived

        # MissionManager polls Supabase for pending missions & feeds Navigator
        self.mission_manager = MissionManager(
            navigator=self.navigator,
            supabase_client=self.supabase,
            health=self.health,
        )
        self.measurement_manager._mission_mgr = self.mission_manager

        # STM32 UART Worker handles incoming telemetry & provides write access to motor controller
        self.stm32 = STM32Worker(
            on_packet=self.measurement_manager.on_stm32_packet,
            motor_controller=self.motor,
            health=self.health,
            on_disconnect=self.motor.force_unknown,
        )

        # Cloud uploader asynchronously syncs sessions and readings to Supabase
        self.uploader = UploaderWorker(
            sqlite_manager=self.db,
            supabase_client=self.supabase,
            health=self.health,
        )

        self._stop_event = threading.Event()

    def start(self) -> None:
        logger.info("Starting all subsystems...")
        self.mqtt.start()
        self.grid_sync.start()
        self.gps.start()
        self.motor.start()
        self.navigator.start()
        self.mission_manager.start()
        self.stm32.start()
        self.uploader.start()
        logger.info("All subsystems successfully started.")

    def stop(self) -> None:
        logger.info("Initiating graceful shutdown...")
        # Emergency stop motors first!
        try:
            self.motor.stop_motors()
        except Exception:
            pass

        workers = [
            ("navigator", self.navigator),
            ("mission_manager", self.mission_manager),
            ("stm32", self.stm32),
            ("motor", self.motor),
            ("gps", self.gps),
            ("grid_sync", self.grid_sync),
            ("uploader", self.uploader),
        ]
        for name, worker in workers:
            try:
                worker.stop()
            except Exception as exc:
                logger.error("Error stopping %s: %s", name, exc)

        try:
            self.mqtt.stop()
        except Exception:
            pass

        try:
            self.db.close()
        except Exception:
            pass

        logger.info("Shutdown complete.")

    def run_forever(self) -> None:
        def _handle_signal(signum, _frame):
            logger.info("Signal %s received — stopping application", signum)
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
