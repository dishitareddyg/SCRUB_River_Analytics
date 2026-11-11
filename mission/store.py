"""
mission/store.py

Atomic persistence of the active mission payload to waypoints.json.

write: temp file in the same directory -> flush + fsync -> os.replace()
       -> fsync directory (POSIX).  A crash at any point leaves either the
       old file or the new file, never a partially written one.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Optional

from config.settings import settings
from monitoring.logger import get_logger

logger = get_logger(__name__)


class WaypointFileStore:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = os.path.abspath(path or settings.WAYPOINT_JSON_PATH)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def write(self, payload: dict) -> None:
        directory = os.path.dirname(self.path)
        fd, tmp = tempfile.mkstemp(prefix=".waypoints.", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        if hasattr(os, "O_DIRECTORY"):  # make the rename durable on Linux
            dir_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        logger.info("waypoints.json written (%s, %d waypoints)",
                    payload.get("mission_id"), len(payload.get("waypoints", [])))

    def read(self) -> Optional[dict]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else None
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("waypoints.json unreadable: %s", exc)
            return None
