"""Retention utilities for historical sensor readings.

Per this module's requirements, raw sensor readings are retained
indefinitely for now - **nothing in this module deletes or aggregates
data automatically**. This file only provides the building blocks
(count, export/archive, purge) that a future scheduled job or admin
tool can call explicitly once a retention policy is decided.

No downsampling/aggregation is implemented here (explicitly out of
scope for this module).
"""

from __future__ import annotations

import csv
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.database.crud import SensorReadingRepository
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ArchiveResult:
    """Outcome of an archive-to-file operation.

    Attributes:
        file_path: Path the archive was written to.
        row_count: Number of readings written to the archive.
        cutoff: The cutoff timestamp used to select rows.
    """

    file_path: Path
    row_count: int
    cutoff: datetime


class RetentionManager:
    """Provides opt-in helpers for archiving and purging old readings.

    Nothing here runs on a schedule or is invoked automatically - a
    future module (or an operator) decides when/whether to call
    these methods.
    """

    def __init__(self, session: Session) -> None:
        """Initialize the manager.

        Args:
            session: An active SQLAlchemy session, managed by the
                caller.
        """
        self._session = session
        self._readings = SensorReadingRepository(session)

    def count_older_than(
        self, cutoff: datetime, device_id: Optional[uuid.UUID] = None
    ) -> int:
        """Count how many readings would be affected by a given cutoff.

        Args:
            cutoff: Only readings with ``timestamp < cutoff`` count.
            device_id: Optional device filter.

        Returns:
            The number of matching readings.
        """
        return self._readings.count_before(cutoff, device_id=device_id)

    def archive_to_csv(
        self, cutoff: datetime, output_path: Path, batch_size: int = 5000
    ) -> ArchiveResult:
        """Export all readings older than ``cutoff`` to a CSV file.

        This does NOT delete the exported rows - call
        :meth:`purge_older_than` separately (and only after confirming
        the archive is valid) if deletion is also desired.

        Args:
            cutoff: Only readings with ``timestamp < cutoff`` are
                exported.
            output_path: Destination CSV file path. Parent
                directories are created if needed.
            batch_size: Page size used while streaming rows out of the
                database, to avoid loading everything into memory at
                once.

        Returns:
            An :class:`ArchiveResult` describing what was written.
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        row_count = 0
        with output_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "id",
                    "timestamp",
                    "device_id",
                    "sensor_id",
                    "value",
                    "raw_value",
                    "quality_score",
                    "validation_status",
                    "packet_sequence",
                ]
            )

            page = 1
            while True:
                result = self._readings.get_before(cutoff, page=page, page_size=batch_size)
                if not result.items:
                    break
                for reading in result.items:
                    writer.writerow(
                        [
                            str(reading.id),
                            reading.timestamp.isoformat(),
                            str(reading.device_id),
                            str(reading.sensor_id),
                            reading.value,
                            json.dumps(reading.raw_value) if reading.raw_value is not None else "",
                            reading.quality_score,
                            reading.validation_status,
                            reading.packet_sequence,
                        ]
                    )
                    row_count += 1
                if page >= result.total_pages:
                    break
                page += 1

        logger.info(f"Archived {row_count} sensor readings older than {cutoff.isoformat()} to {output_path}")
        return ArchiveResult(file_path=output_path, row_count=row_count, cutoff=cutoff)

    def purge_older_than(self, cutoff: datetime) -> int:
        """Permanently delete all readings older than ``cutoff``.

        This is destructive and irreversible. Callers should archive
        data first (see :meth:`archive_to_csv`) if the data may be
        needed later. Not invoked automatically anywhere in this
        codebase.

        Args:
            cutoff: Readings with ``timestamp < cutoff`` are deleted.

        Returns:
            The number of rows deleted.
        """
        deleted = self._readings.delete_older_than(cutoff)
        logger.warning(f"Purged {deleted} sensor readings older than {cutoff.isoformat()}")
        return deleted
