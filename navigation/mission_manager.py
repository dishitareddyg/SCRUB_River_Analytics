"""
navigation/mission_manager.py

Fetches missions from Supabase and feeds them to the Navigator.

A "mission" in Supabase is a row in the `missions` table (status=PENDING
or ACTIVE) with an associated ordered list of grid waypoints in
`mission_grids`.  The frontend creates this record; this worker polls
Supabase and, when a PENDING mission is found for this device, activates
it:
  1. Fetches the ordered waypoints (grid_id, sequence_order, center_lat,
     center_lon, grid_code from the joined grids table).
  2. Loads them into the Navigator.
  3. Calls navigator.cmd_start().
  4. Updates the mission status to ACTIVE in Supabase.

When the Navigator transitions to COMPLETE or ERROR, this worker marks
the Supabase mission accordingly and then polls for the next one.

Grid waypoints progress (mission_grids.status) is updated as the bot
arrives at and completes each grid — this gives the frontend real-time
per-grid visibility.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from config.settings import settings
from monitoring.logger import get_logger
from navigation.navigator import Navigator, NavState

logger = get_logger(__name__)


class MissionManager:
    def __init__(self, navigator: Navigator, supabase_client, health=None) -> None:
        self._nav = navigator
        self._supabase = supabase_client
        self._health = health
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._active_mission_id: Optional[str] = None
        self._active_mission_grids: list[dict] = []   # ordered list with mission_grid_id

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="MissionManager", daemon=True
        )
        self._thread.start()
        logger.info("MissionManager started (poll interval=%.0fs)",
                    settings.MISSION_POLL_INTERVAL_SECONDS)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    # ------------------------------------------------------------------
    # Called by the main application when a grid session completes so
    # this manager can update mission_grids.status in Supabase.
    # ------------------------------------------------------------------
    def on_grid_session_complete(self, grid_id: str, session_id: str) -> None:
        if not self._active_mission_id:
            return
        try:
            self._supabase.mark_mission_grid_completed(
                self._active_mission_id, grid_id, session_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to mark mission_grid completed: %s", exc)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_once()
            except Exception as exc:  # noqa: BLE001
                logger.warning("MissionManager poll error: %s", exc)
            self._stop_event.wait(settings.MISSION_POLL_INTERVAL_SECONDS)

    def _poll_once(self) -> None:
        nav_state = self._nav.state

        # If we have an active mission, check if it finished.
        if self._active_mission_id:
            if nav_state == NavState.COMPLETE:
                logger.info("Mission %s COMPLETE", self._active_mission_id)
                try:
                    self._supabase.mark_mission_complete(self._active_mission_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to mark mission complete in Supabase: %s", exc)
                self._active_mission_id = None
                self._active_mission_grids = []

            elif nav_state in (NavState.GPS_LOST, NavState.GEOFENCE_STOP, NavState.ERROR):
                logger.warning(
                    "Mission %s aborted due to %s", self._active_mission_id, nav_state
                )
                try:
                    self._supabase.mark_mission_aborted(
                        self._active_mission_id, reason=nav_state.value
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed to mark mission aborted: %s", exc)
                self._active_mission_id = None
                self._active_mission_grids = []
            else:
                # Mission still running — update navigating grid status.
                self._update_current_grid_status_navigating()
            return

        # No active mission — look for a PENDING one.
        if not self._supabase.available:
            return

        mission = self._supabase.fetch_pending_mission(settings.DEVICE_ID)
        if mission is None:
            return

        mission_id = mission["mission_id"]
        logger.info("New mission found: %s", mission_id)

        waypoints = self._supabase.fetch_mission_waypoints(mission_id)
        if not waypoints:
            logger.warning("Mission %s has no waypoints — skipping", mission_id)
            return

        # Activate
        self._active_mission_id = mission_id
        self._active_mission_grids = waypoints
        self._nav.load_mission(waypoints, mission_id=mission_id)
        self._nav.cmd_start()

        try:
            self._supabase.mark_mission_active(mission_id)
            # Mark the first grid as NAVIGATING.
            if waypoints:
                self._supabase.mark_mission_grid_navigating(
                    mission_id, waypoints[0]["grid_id"]
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Supabase mission activation update failed: %s", exc)

    def _update_current_grid_status_navigating(self) -> None:
        """Keep mission_grids.status = NAVIGATING for the current target."""
        wp = self._nav.current_waypoint
        if wp is None or not self._active_mission_id:
            return
        try:
            self._supabase.mark_mission_grid_navigating(
                self._active_mission_id, wp["grid_id"]
            )
        except Exception:  # noqa: BLE001
            pass
