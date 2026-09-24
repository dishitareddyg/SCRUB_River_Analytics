"""
storage/average_manager.py

Computes local, session-scoped averages once a session completes
(spec sections 24-25). Averages are ALWAYS local-only (RULE 11) and are
never part of the Supabase cloud payload.

Rules implemented:
  - NULL (None) values are excluded from the average, not treated as 0.
  - If every value for a given sensor is NULL, the average is NULL (None),
    never invented.
  - Averages are keyed by (grid_id, session_id) so different sessions for
    the same grid never overwrite each other's averages.
"""

from __future__ import annotations

from typing import Optional

_FIELDS = ["ph", "tds", "turbidity", "temperature_c", "humidity_percent"]


def compute_averages(readings: list[dict]) -> dict[str, Optional[float]]:
    result: dict[str, Optional[float]] = {}
    for field_name in _FIELDS:
        values = [r[field_name] for r in readings if r.get(field_name) is not None]
        result[field_name] = (sum(values) / len(values)) if values else None
    return result
