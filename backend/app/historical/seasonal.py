"""Seasonal grouping - hour/day/week/month/season/year summaries.

Groups already-fetched, in-memory ``(timestamp, value)`` points by a
calendar-derived key (hour-of-day, day-of-week, ISO week, month,
meteorological season, or year) and summarizes each group with the
reusable functions in :mod:`app.historical.statistics`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from app.historical.statistics import average, maximum, minimum, std_dev

_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
# Meteorological (Northern Hemisphere) season convention, grouped by
# calendar month. Documented here since a Southern-Hemisphere
# deployment would need the opposite mapping.
_SEASON_BY_MONTH = {
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
    9: "Autumn", 10: "Autumn", 11: "Autumn",
}
_SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]


class SeasonalGroupBy(str, Enum):
    """The calendar dimension to group historical points by.

    Attributes:
        HOUR: Hour of day, 0-23.
        DAY: Day of week, Monday-Sunday.
        WEEK: ISO calendar week number within the year.
        MONTH: Calendar month, January-December.
        SEASON: Meteorological season (Northern Hemisphere
            convention - see this module's docstring).
        YEAR: Calendar year.
    """

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    SEASON = "season"
    YEAR = "year"


@dataclass(frozen=True)
class SeasonalGroupSummary:
    """Summary statistics for one seasonal group.

    Attributes:
        group_key: A stable, sortable key for this group (e.g. ``"3"``
            for hour-of-day 3, ``"2026-03"`` for March 2026).
        label: A human readable label (e.g. ``"03:00"``, ``"March"``).
        count: Number of points in this group.
        average: Mean value across the group.
        minimum: Minimum value across the group.
        maximum: Maximum value across the group.
        std_dev: Sample standard deviation across the group.
    """

    group_key: str
    label: str
    count: int
    average: Optional[float]
    minimum: Optional[float]
    maximum: Optional[float]
    std_dev: Optional[float]


def _group_key_and_label(timestamp: datetime, group_by: SeasonalGroupBy) -> Tuple[str, str]:
    """Compute a group's sort key and display label for one timestamp.

    Args:
        timestamp: A timezone-aware UTC timestamp.
        group_by: The calendar dimension to group by.

    Returns:
        A ``(group_key, label)`` pair. ``group_key`` sorts correctly
        as a plain string within a given ``group_by``.
    """
    ts = timestamp.astimezone(timezone.utc)

    if group_by is SeasonalGroupBy.HOUR:
        key = f"{ts.hour:02d}"
        return key, f"{ts.hour:02d}:00"

    if group_by is SeasonalGroupBy.DAY:
        weekday = ts.weekday()  # 0 = Monday
        return str(weekday), _DAY_NAMES[weekday]

    if group_by is SeasonalGroupBy.WEEK:
        iso_year, iso_week, _ = ts.isocalendar()
        key = f"{iso_year}-W{iso_week:02d}"
        return key, key

    if group_by is SeasonalGroupBy.MONTH:
        key = f"{ts.month:02d}"
        return key, _MONTH_NAMES[ts.month - 1]

    if group_by is SeasonalGroupBy.SEASON:
        season = _SEASON_BY_MONTH[ts.month]
        key = str(_SEASON_ORDER.index(season))
        return key, season

    # YEAR
    return str(ts.year), str(ts.year)


def group_seasonal(
    points: Sequence[Tuple[datetime, float]], group_by: SeasonalGroupBy
) -> List[SeasonalGroupSummary]:
    """Group ``points`` by ``group_by`` and summarize each group.

    Args:
        points: ``(timestamp, value)`` pairs, in any order.
        group_by: The calendar dimension to group by.

    Returns:
        One :class:`SeasonalGroupSummary` per non-empty group,
        ordered by ``group_key``.
    """
    groups: Dict[str, Tuple[str, List[float]]] = {}
    for timestamp, value in points:
        if value is None:
            continue
        key, label = _group_key_and_label(timestamp, group_by)
        if key not in groups:
            groups[key] = (label, [])
        groups[key][1].append(value)

    result: List[SeasonalGroupSummary] = []
    for key in sorted(groups):
        label, values = groups[key]
        result.append(
            SeasonalGroupSummary(
                group_key=key,
                label=label,
                count=len(values),
                average=average(values),
                minimum=minimum(values),
                maximum=maximum(values),
                std_dev=std_dev(values),
            )
        )
    return result


__all__ = ["SeasonalGroupBy", "SeasonalGroupSummary", "group_seasonal"]
