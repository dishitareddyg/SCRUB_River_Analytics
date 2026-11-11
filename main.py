#!/usr/bin/env python3
"""
main.py — Autonomous Lake Cleaning Bot backend (Raspberry Pi 5).

Threads / workers:
  STM32Worker            UART reader (1 packet / 2 s) -> PacketRouter
  MotorControllerWorker  UART writer (1 motor packet / 2 s, documented format)
  Navigator              global GPS waypoint follower (GCS -> polygon -> GCS)
  SensorSnapshotWorker   1 GPS-tagged sensor snapshot / 10 s -> SQLite
  SensorUploader         <= 1 record / 10 s -> Supabase (offline-first)
  MissionSyncWorker      mission metadata / progress -> Supabase
  TelemetryHub           live MQTT telemetry; WebSocket via FastAPI
  FastAPI (uvicorn)      mission API + /ws/telemetry (main thread)

Startup never moves the motors: missions found ACTIVE after a reboot are
set to PAUSED and wait for an explicit operator resume.
"""

from __future__ import annotations

import signal
import sys
import threading

from cloud.supabase_client import SupabaseClientWrapper
from cloud.uploader import MissionSyncWorker, SensorUploader
from communication.mqtt_client import MQTTClient
from communication.telemetry import TelemetryHub
from config.settings import settings
from hardware.gps import GPSWorker
from hardware.live_state import LiveState, PacketRouter
from hardware.motor_controller import MotorControllerWorker
from hardware.stm32 import STM32Worker
from measurement.sensor_validator import SensorValidator
from measurement.snapshot_worker import SensorSnapshotWorker
from mission.manager import MissionManager
from mission.store import WaypointFileStore
from monitoring.health import HealthMonitor
from monitoring.logger import get_logger
from navigation.navigator import Navigator
from storage.sqlite_manager import SQLiteManager

logger = get_logger(__name__)


class Application:
    def __init__(self) -> None:
        logger.info("Initializing Lake Bot backend (device_id=%s)", settings.DEVICE_ID)
        self.health = HealthMonitor()
        self.db = SQLiteManager()
        self.supabase = SupabaseClientWrapper()
        self.mqtt = MQTTClient(health=self.health) if settings.MQTT_ENABLED else None

        self.gps = GPSWorker(health=self.health)
        self.motor = MotorControllerWorker(health=self.health)
        self.live_state = LiveState()
        self.router = PacketRouter(self.gps, self.motor, self.live_state, SensorValidator(), self.health)
        self.stm32 = STM32Worker(
            on_packet=self.router.on_stm32_packet,
            motor_controller=self.motor,
            health=self.health,
            on_disconnect=self.motor.force_unknown,
        )
        link_ok = lambda: self.stm32.link_alive  # noqa: E731

        self.navigator = Navigator(self.gps, self.motor, self.health, link_ok=link_ok)
        self.mission_sync = MissionSyncWorker(self.db, self.supabase, self.health)
        self.missions = MissionManager(
            self.db, self.navigator, self.motor, self.gps,
            store=WaypointFileStore(), link_ok=link_ok, on_change=self._on_mission_change,
        )
        self.snapshots = SensorSnapshotWorker(
            self.db, self.live_state, self.gps, self.missions.current_mission_id, self.health
        )
        self.uploader = SensorUploader(self.db, self.supabase, self.health)
        self.telemetry = TelemetryHub(
            gps=self.gps, motor=self.motor, live_state=self.live_state, navigator=self.navigator,
            mission_manager=self.missions, stm32=self.stm32, db=self.db,
            uploader=self.uploader, mqtt=self.mqtt,
        )
        self._stop_event = threading.Event()
        self._health_thread: threading.Thread | None = None

    def _on_mission_change(self, mission: dict) -> None:
        self.mission_sync.notify()
        if self.mqtt:
            self.mqtt.publish(settings.MQTT_TOPIC_MISSION, {
                k: mission.get(k) for k in ("mission_id", "status", "current_waypoint_index",
                                            "total_waypoints", "progress_percent", "notes")
            })

    # ------------------------------------------------------------------
    def start(self) -> None:
        recovered = self.missions.recover_after_restart()   # never restarts motion
        if recovered:
            logger.warning("Recovered %d mission(s); operator authorisation required", len(recovered))
        if self.mqtt:
            self.mqtt.start()
        self.motor.start()        # starts sending "+0" packets every 2 s
        self.stm32.start()
        self.navigator.start()
        self.snapshots.start()
        self.uploader.start()
        self.mission_sync.start()
        self.telemetry.start()
        self._health_thread = threading.Thread(target=self._health_loop, name="HealthPublisher", daemon=True)
        self._health_thread.start()
        logger.info("All subsystems started.")

    def _health_loop(self) -> None:
        while not self._stop_event.wait(settings.HEALTH_PUBLISH_INTERVAL_SECONDS):
            if self.mqtt:
                self.mqtt.publish(settings.MQTT_TOPIC_HEALTH, self.health.snapshot())

    def stop(self) -> None:
        logger.info("Graceful shutdown: stopping motors first...")
        self._stop_event.set()
        try:
            self.motor.emergency_stop()
        except Exception:  # noqa: BLE001
            pass
        for name, worker in (
            ("navigator", self.navigator),
            ("telemetry", self.telemetry),
            ("snapshots", self.snapshots),
            ("uploader", self.uploader),
            ("mission_sync", self.mission_sync),
            ("motor", self.motor),      # sends a final zero packet
            ("stm32", self.stm32),      # closes the UART last
        ):
            try:
                worker.stop()
            except Exception as exc:  # noqa: BLE001
                logger.error("Error stopping %s: %s", name, exc)
        if self.mqtt:
            try:
                self.mqtt.stop()
            except Exception:  # noqa: BLE001
                pass
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        logger.info("Shutdown complete.")

    # ------------------------------------------------------------------
    def run_forever(self) -> None:
        self.start()
        try:
            if settings.API_ENABLED and self._run_api():
                return
            # API disabled/unavailable: wait for a signal.
            def _handle(signum, _frame):
                logger.info("Signal %s received", signum)
                self._stop_event.set()
            signal.signal(signal.SIGINT, _handle)
            signal.signal(signal.SIGTERM, _handle)
            while not self._stop_event.wait(1.0):
                pass
        finally:
            self.stop()

    def _run_api(self) -> bool:
        try:
            import uvicorn

            from api.app import create_app
        except ImportError as exc:
            logger.error("FastAPI/uvicorn not installed (%s) — running without HTTP API", exc)
            return False
        app = create_app(self)
        config = uvicorn.Config(app, host=settings.API_HOST, port=settings.API_PORT,
                                log_level=settings.LOG_LEVEL.lower(), proxy_headers=True)
        server = uvicorn.Server(config)
        logger.info("HTTP API listening on %s:%d", settings.API_HOST, settings.API_PORT)
        server.run()  # handles SIGINT/SIGTERM and returns
        return True


def main() -> int:
    Application().run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
