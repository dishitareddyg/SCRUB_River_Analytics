"""Parameter comparison utilities.

Lets any future module compare two arbitrary historical series (e.g.
``DO`` vs ``Temperature``, ``Conductivity`` vs ``TDS``, ``Rainfall``
vs ``Water Level``) without knowing anything about how those series
were produced - :func:`compare_series` only needs two lists of
``(timestamp, value)`` points.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from app.historical.aggregation import AggregationInterval, aggregate_series
from app.historical.statistics import average, maximum, minimum, std_dev

#: Default alignment granularity used to match up two independently
#: sampled series before computing correlation (see
#: :func:`compare_series`).
_DEFAULT_ALIGNMENT = AggregationInterval.HOURLY


@dataclass(frozen=True)
class SeriesSummary:
    """A compact statistical summary for one side of a comparison.

    Attributes:
        count: Number of raw points contributed by this series.
        average: Mean value.
        minimum: Minimum value.
        maximum: Maximum value.
        std_dev: Sample standard deviation.
    """

    count: int
    average: Optional[float]
    minimum: Optional[float]
    maximum: Optional[float]
    std_dev: Optional[float]


@dataclass(frozen=True)
class ComparisonResult:
    """The result of comparing two historical parameter series.

    Attributes:
        parameter_a: Summary of the first series.
        parameter_b: Summary of the second series.
        matched_points: Number of aligned ``(a, b)`` sample pairs the
            correlation was computed from (see this module's
            docstring on alignment).
        correlation: Pearson correlation coefficient between the two
            aligned series, in ``[-1.0, 1.0]``, or ``None`` if fewer
            than 2 matched points exist or either series has zero
            variance.
    """

    parameter_a: SeriesSummary
    parameter_b: SeriesSummary
    matched_points: int
    correlation: Optional[float]


def _summarize(points: Sequence[Tuple[object, float]]) -> SeriesSummary:
    """Build a :class:`SeriesSummary` from raw ``(timestamp, value)`` points.

    Args:
        points: ``(timestamp, value)`` pairs.

    Returns:
        A :class:`SeriesSummary` of the values.
    """
    values = [value for _, value in points if value is not None]
    return SeriesSummary(
        count=len(values),
        average=average(values),
        minimum=minimum(values),
        maximum=maximum(values),
        std_dev=std_dev(values),
    )


def pearson_correlation(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Compute the Pearson correlation coefficient between two equal-length series.

    Args:
        xs: First series of values.
        ys: Second series of values, aligned index-for-index with ``xs``.

    Returns:
        The correlation coefficient in ``[-1.0, 1.0]``, or ``None`` if
        fewer than 2 points are given or either series has zero
        variance (a constant series has no defined correlation).
    """
    n = len(xs)
    if n < 2 or len(ys) != n:
        return None

    mean_x = sum(xs) / n
    mean_y = sum(ys) / n

    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    ss_yy = sum((y - mean_y) ** 2 for y in ys)
    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))

    if ss_xx == 0 or ss_yy == 0:
        return None

    return ss_xy / (ss_xx**0.5 * ss_yy**0.5)


def compare_series(
    points_a: Sequence[Tuple[object, float]],
    points_b: Sequence[Tuple[object, float]],
    *,
    alignment: AggregationInterval = _DEFAULT_ALIGNMENT,
) -> ComparisonResult:
    """Compare two historical series, including their correlation.

    Two sensors are rarely sampled at identical instants, so
    correlation is computed on *aligned* buckets rather than raw
    points: both series are independently aggregated (mean) into
    ``alignment``-sized buckets (see
    :func:`app.historical.aggregation.aggregate_series`), then only
    buckets present in *both* series are paired up for the Pearson
    correlation calculation. Overall summary statistics
    (min/max/mean/std-dev/count), however, are still computed from
    each series' full, unaligned set of raw points.

    Args:
        points_a: ``(timestamp, value)`` pairs for the first parameter.
        points_b: ``(timestamp, value)`` pairs for the second parameter.
        alignment: The bucket granularity used to align the two series
            before computing correlation. Defaults to hourly.

    Returns:
        A :class:`ComparisonResult`.
    """
    summary_a = _summarize(points_a)
    summary_b = _summarize(points_b)

    buckets_a: Dict[object, float] = {
        bucket.period_start: bucket.average for bucket in aggregate_series(points_a, alignment)
    }
    buckets_b: Dict[object, float] = {
        bucket.period_start: bucket.average for bucket in aggregate_series(points_b, alignment)
    }

    shared_keys = sorted(set(buckets_a) & set(buckets_b))
    aligned_a = [buckets_a[key] for key in shared_keys]
    aligned_b = [buckets_b[key] for key in shared_keys]

    correlation = pearson_correlation(aligned_a, aligned_b)

    return ComparisonResult(
        parameter_a=summary_a,
        parameter_b=summary_b,
        matched_points=len(shared_keys),
        correlation=correlation,
    )


__all__ = [
    "SeriesSummary",
    "ComparisonResult",
    "pearson_correlation",
    "compare_series",
]

# Re-exported for callers that want to reference the default alignment
# without importing app.historical.aggregation directly.
DEFAULT_ALIGNMENT: AggregationInterval = _DEFAULT_ALIGNMENT
