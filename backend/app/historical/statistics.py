"""Reusable statistical summary functions.

Every function here operates on plain ``List[float]`` (or, where
noted, ``List[Optional[float]]``) so it has zero dependency on the
database layer, HTTP layer, or any particular time-series
representation - :mod:`app.historical.service` is the only caller
that knows about sensors, parameters, or time ranges.

Deliberately implemented with the standard library only (``statistics``
/ ``math``), per this module's "must remain lightweight" requirement -
no ``numpy``/``pandas`` dependency is introduced here.
"""

from __future__ import annotations

import statistics as _stats
from typing import List, Optional, Sequence


def minimum(values: Sequence[float]) -> Optional[float]:
    """Return the smallest value in ``values``.

    Args:
        values: Numeric values.

    Returns:
        The minimum value, or ``None`` if ``values`` is empty.
    """
    return min(values) if values else None


def maximum(values: Sequence[float]) -> Optional[float]:
    """Return the largest value in ``values``.

    Args:
        values: Numeric values.

    Returns:
        The maximum value, or ``None`` if ``values`` is empty.
    """
    return max(values) if values else None


def average(values: Sequence[float]) -> Optional[float]:
    """Return the arithmetic mean of ``values``.

    Args:
        values: Numeric values.

    Returns:
        The mean, or ``None`` if ``values`` is empty.
    """
    return _stats.fmean(values) if values else None


def median(values: Sequence[float]) -> Optional[float]:
    """Return the median of ``values``.

    Args:
        values: Numeric values.

    Returns:
        The median, or ``None`` if ``values`` is empty.
    """
    return _stats.median(values) if values else None


def std_dev(values: Sequence[float], sample: bool = True) -> Optional[float]:
    """Return the standard deviation of ``values``.

    Args:
        values: Numeric values.
        sample: If ``True`` (default), compute the sample standard
            deviation (``n - 1`` denominator). If ``False``, compute
            the population standard deviation (``n`` denominator).

    Returns:
        The standard deviation. ``None`` if ``values`` is empty, and
        ``0.0`` if it has a single element and ``sample`` is ``True``
        (a single sample has no defined sample variance, but ``0.0``
        is the conventional, UI-friendly answer rather than raising).
    """
    if not values:
        return None
    if len(values) == 1:
        return 0.0
    return _stats.stdev(values) if sample else _stats.pstdev(values)


def variance(values: Sequence[float], sample: bool = True) -> Optional[float]:
    """Return the variance of ``values``.

    Args:
        values: Numeric values.
        sample: If ``True`` (default), compute the sample variance
            (``n - 1`` denominator). If ``False``, compute the
            population variance (``n`` denominator).

    Returns:
        The variance. ``None`` if ``values`` is empty, ``0.0`` if it
        has a single element and ``sample`` is ``True``.
    """
    if not values:
        return None
    if len(values) == 1:
        return 0.0
    return _stats.variance(values) if sample else _stats.pvariance(values)


def percent_change(first: Optional[float], last: Optional[float]) -> Optional[float]:
    """Return the percentage change from ``first`` to ``last``.

    Args:
        first: The starting value.
        last: The ending value.

    Returns:
        ``(last - first) / abs(first) * 100``, or ``None`` if either
        value is ``None`` or ``first`` is ``0`` (percent change is
        undefined relative to a zero baseline).
    """
    if first is None or last is None or first == 0:
        return None
    return (last - first) / abs(first) * 100.0


def first_value(values: Sequence[float]) -> Optional[float]:
    """Return the first value in a chronologically ordered sequence.

    Args:
        values: Numeric values, oldest first.

    Returns:
        The first value, or ``None`` if ``values`` is empty.
    """
    return values[0] if values else None


def last_value(values: Sequence[float]) -> Optional[float]:
    """Return the last value in a chronologically ordered sequence.

    Args:
        values: Numeric values, oldest first.

    Returns:
        The last value, or ``None`` if ``values`` is empty.
    """
    return values[-1] if values else None


def count(values: Sequence[float]) -> int:
    """Return the number of values.

    Args:
        values: Numeric values.

    Returns:
        ``len(values)``.
    """
    return len(values)


def missing_value_count(raw_values: Sequence[Optional[float]]) -> int:
    """Count how many entries in ``raw_values`` are missing (``None``).

    Args:
        raw_values: A sequence that may contain ``None`` entries
            (e.g. every reading fetched for a range, before dropping
            non-numeric ones).

    Returns:
        The number of ``None`` entries.
    """
    return sum(1 for value in raw_values if value is None)


def rolling_mean(values: Sequence[float], window: int) -> List[Optional[float]]:
    """Compute a trailing rolling mean over ``values``.

    Args:
        values: Numeric values, oldest first.
        window: Window size, in number of samples. Must be >= 1.

    Returns:
        A list the same length as ``values``, where index ``i`` holds
        the mean of ``values[max(0, i - window + 1):i + 1]`` once at
        least ``window`` samples are available, and ``None`` for the
        leading positions that don't yet have a full window.

    Raises:
        ValueError: If ``window`` is less than 1.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    result: List[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < window:
            result.append(None)
        else:
            result.append(_stats.fmean(values[i + 1 - window : i + 1]))
    return result


def rolling_std(values: Sequence[float], window: int, sample: bool = True) -> List[Optional[float]]:
    """Compute a trailing rolling standard deviation over ``values``.

    Args:
        values: Numeric values, oldest first.
        window: Window size, in number of samples. Must be >= 1.
        sample: If ``True`` (default), use the sample standard
            deviation within each window; otherwise the population
            standard deviation.

    Returns:
        A list the same length as ``values``, following the same
        alignment convention as :func:`rolling_mean`.

    Raises:
        ValueError: If ``window`` is less than 1.
    """
    if window < 1:
        raise ValueError("window must be >= 1")
    result: List[Optional[float]] = []
    for i in range(len(values)):
        if i + 1 < window:
            result.append(None)
        else:
            windowed = values[i + 1 - window : i + 1]
            result.append(std_dev(windowed, sample=sample))
    return result


# "Moving Average" is the same concept as "Rolling Mean" - kept as a
# named alias (rather than a second implementation) to satisfy this
# module's "No Duplicate Logic" coding standard while still exposing
# both vocabulary terms called for in the module's requirements.
moving_average = rolling_mean
