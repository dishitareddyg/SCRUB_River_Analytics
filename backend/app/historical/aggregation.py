"""Data aggregation into hourly/daily/weekly/monthly buckets.

Reads already-fetched, in-memory ``(timestamp, value)`` points and
groups them into fixed-size time buckets, returning one summarized
:class:`AggregatedBucket` per bucket. This module never touches the
database and never mutates its input - it only aggregates *derived*
in-memory series; the raw ``sensor_readings`` table is never modified
(and this module has no write path to it at all).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple

from app.historical.statistics import average, maximum, minimum, std_dev


class AggregationInterval(str, Enum):
    """A supported aggregation bucket size.

    Attributes:
        HOURLY: One bucket per calendar hour.
        DAILY: One bucket per calendar day (UTC).
        WEEKLY: One bucket per ISO week (Monday start, UTC).
        MONTHLY: One bucket per calendar month (UTC).
    """

    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass(frozen=True)
class AggregatedBucket:
    """One aggregated time bucket.

    Attributes:
        period_start: Inclusive start of the bucket (UTC).
        period_end: Exclusive end of the bucket (UTC).
        count: Number of raw points that fell in this bucket.
        average: Mean value across the bucket.
        minimum: Minimum value across the bucket.
        maximum: Maximum value across the bucket.
        std_dev: Sample standard deviation across the bucket.
    """

    period_start: datetime
    period_end: datetime
    count: int
    average: Optional[float]
    minimum: Optional[float]
    maximum: Optional[float]
    std_dev: Optional[float]


def _bucket_start(timestamp: datetime, interval: AggregationInterval) -> datetime:
    """Truncate ``timestamp`` down to the start of its bucket.

    Args:
        timestamp: A timezone-aware UTC timestamp.
        interval: The aggregation granularity.

    Returns:
        The bucket's inclusive start timestamp.
    """
    ts = timestamp.astimezone(timezone.utc)
    if interval is AggregationInterval.HOURLY:
        return ts.replace(minute=0, second=0, microsecond=0)
    if interval is AggregationInterval.DAILY:
        return ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if interval is AggregationInterval.WEEKLY:
        day_start = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start - timedelta(days=day_start.weekday())  # Monday start
    # MONTHLY
    return ts.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _bucket_end(bucket_start: datetime, interval: AggregationInterval) -> datetime:
    """Compute a bucket's exclusive end timestamp.

    Args:
        bucket_start: The bucket's inclusive start (as returned by
            :func:`_bucket_start`).
        interval: The aggregation granularity.

    Returns:
        The bucket's exclusive end timestamp.
    """
    if interval is AggregationInterval.HOURLY:
        return bucket_start + timedelta(hours=1)
    if interval is AggregationInterval.DAILY:
        return bucket_start + timedelta(days=1)
    if interval is AggregationInterval.WEEKLY:
        return bucket_start + timedelta(weeks=1)
    # MONTHLY
    if bucket_start.month == 12:
        return bucket_start.replace(year=bucket_start.year + 1, month=1)
    return bucket_start.replace(month=bucket_start.month + 1)


def aggregate_series(
    points: Sequence[Tuple[datetime, float]], interval: AggregationInterval
) -> List[AggregatedBucket]:
    """Group ``points`` into buckets and summarize each one.

    Args:
        points: ``(timestamp, value)`` pairs, in any order.
        interval: The aggregation granularity.

    Returns:
        One :class:`AggregatedBucket` per non-empty bucket that
        contains at least one point, ordered chronologically.
    """
    buckets: Dict[datetime, List[float]] = {}
    for timestamp, value in points:
        if value is None:
            continue
        key = _bucket_start(timestamp, interval)
        buckets.setdefault(key, []).append(value)

    result: List[AggregatedBucket] = []
    for bucket_start in sorted(buckets):
        values = buckets[bucket_start]
        result.append(
            AggregatedBucket(
                period_start=bucket_start,
                period_end=_bucket_end(bucket_start, interval),
                count=len(values),
                average=average(values),
                minimum=minimum(values),
                maximum=maximum(values),
                std_dev=std_dev(values),
            )
        )
    return result


__all__ = ["AggregationInterval", "AggregatedBucket", "aggregate_series"]
