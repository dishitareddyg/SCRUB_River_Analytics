"""Reusable, configurable feature engineering over a pandas DataFrame.

Every function here takes and returns plain :class:`pandas.DataFrame`/
:class:`pandas.Series` objects indexed by a timezone-aware UTC
:class:`~pandas.DatetimeIndex` (as produced by
:mod:`app.ml.dataset_builder`) - this module has no knowledge of the
database, HTTP layer, or any particular parameter's meaning, so it can
be reused unchanged by every model in this package.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Northern Hemisphere meteorological season convention, grouped by
#: calendar month - matches app.historical.seasonal's convention for
#: consistency across the platform (kept as a small local copy rather
#: than importing a private constant from that module).
_SEASON_BY_MONTH = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
}
_SEASON_CODES = {"winter": 0, "spring": 1, "summer": 2, "autumn": 3}

#: Parameter -> engineered "change" feature name, for the specific
#: named change features called for in this module's requirements
#: (rainfall change, temperature difference, water level change, DO
#: change, conductivity change). Any other column can still get a
#: generic ``<column>_change`` feature via ``diff_columns``.
NAMED_CHANGE_FEATURES: Dict[str, str] = {
    "rainfall": "rainfall_change",
    "water_temperature": "temperature_difference",
    "water_level": "water_level_change",
    "dissolved_oxygen": "do_change",
    "conductivity": "conductivity_change",
}


@dataclass
class FeatureConfig:
    """Configures which feature families :func:`build_features` generates.

    Attributes:
        target_columns: Columns to generate rolling/lag/rate-of-change
            features for. Defaults to every numeric column in the
            input frame if left ``None``.
        roll_windows: Window sizes (in rows) for rolling mean/std
            features, e.g. ``[3, 24]`` for a short and a daily
            (hourly-resampled) window.
        lag_counts: Number of previous values (in rows) to include as
            ``<column>_lag_<n>`` features, e.g. ``3`` adds lag 1, 2,
            and 3.
        include_rate_of_change: Add a ``<column>_roc`` percent-change-
            from-previous-row feature per target column.
        include_change_features: Add the named "change" features (see
            :data:`NAMED_CHANGE_FEATURES`) for any matching column
            present in the input frame.
        include_calendar_features: Add ``day_of_week`` (0=Monday),
            ``month`` (1-12), and ``season`` (0=winter..3=autumn)
            features derived from the index.
        dropna: Drop rows containing ``NaN`` introduced by rolling/lag
            windows (i.e. the leading rows that don't yet have a full
            window) before returning.
    """

    target_columns: Optional[List[str]] = None
    roll_windows: List[int] = field(default_factory=lambda: [3, 24])
    lag_counts: int = 3
    include_rate_of_change: bool = True
    include_change_features: bool = True
    include_calendar_features: bool = True
    dropna: bool = True


def add_rolling_mean(df: pd.DataFrame, column: str, window: int) -> pd.Series:
    """Compute a trailing rolling mean ("Moving Average"/"Rolling Mean").

    Args:
        df: The source frame.
        column: Column to roll over.
        window: Window size, in rows.

    Returns:
        A :class:`pandas.Series` named ``"<column>_roll_mean_<window>"``.
    """
    return df[column].rolling(window=window, min_periods=window).mean().rename(f"{column}_roll_mean_{window}")


def add_rolling_std(df: pd.DataFrame, column: str, window: int) -> pd.Series:
    """Compute a trailing rolling standard deviation.

    Args:
        df: The source frame.
        column: Column to roll over.
        window: Window size, in rows.

    Returns:
        A :class:`pandas.Series` named ``"<column>_roll_std_<window>"``.
    """
    return df[column].rolling(window=window, min_periods=window).std().rename(f"{column}_roll_std_{window}")


def add_rate_of_change(df: pd.DataFrame, column: str) -> pd.Series:
    """Compute row-over-row percent change ("Rate of Change").

    Args:
        df: The source frame.
        column: Column to compute rate of change for.

    Returns:
        A :class:`pandas.Series` named ``"<column>_roc"``, in percent.
    """
    return (df[column].pct_change() * 100.0).rename(f"{column}_roc")


def add_lag_features(df: pd.DataFrame, column: str, lags: int) -> pd.DataFrame:
    """Add ``lags`` previous-value columns ("Previous N values").

    Args:
        df: The source frame.
        column: Column to lag.
        lags: Number of lags to generate (``1..lags``).

    Returns:
        A new :class:`pandas.DataFrame` with columns
        ``"<column>_lag_1"..."<column>_lag_<lags>"``.
    """
    return pd.DataFrame({f"{column}_lag_{n}": df[column].shift(n) for n in range(1, lags + 1)}, index=df.index)


def add_change_feature(df: pd.DataFrame, column: str, feature_name: Optional[str] = None) -> pd.Series:
    """Add a generic row-over-row absolute difference ("<parameter> Change").

    Args:
        df: The source frame.
        column: Column to difference.
        feature_name: Output column name. Defaults to
            ``"<column>_change"``, or the platform-standard name in
            :data:`NAMED_CHANGE_FEATURES` when ``column`` is one of
            the specifically named parameters (rainfall, water
            temperature, water level, DO, conductivity).

    Returns:
        A :class:`pandas.Series` of ``df[column].diff()``.
    """
    name = feature_name or NAMED_CHANGE_FEATURES.get(column, f"{column}_change")
    return df[column].diff().rename(name)


def add_calendar_features(df: pd.DataFrame) -> pd.DataFrame:
    """Derive Day of Week / Month / Season features from the index.

    Args:
        df: A frame indexed by a :class:`~pandas.DatetimeIndex`.

    Returns:
        A new :class:`pandas.DataFrame` with integer columns
        ``day_of_week`` (0=Monday..6=Sunday), ``month`` (1-12), and
        ``season`` (0=winter, 1=spring, 2=summer, 3=autumn - Northern
        Hemisphere convention, matching
        ``app.historical.seasonal``'s), indexed like ``df``.
    """
    index = df.index
    return pd.DataFrame(
        {
            "day_of_week": index.dayofweek,
            "month": index.month,
            "season": [_SEASON_CODES[_SEASON_BY_MONTH[m]] for m in index.month],
        },
        index=index,
    )


def build_features(df: pd.DataFrame, config: Optional[FeatureConfig] = None) -> pd.DataFrame:
    """Generate every configured feature family and append it to ``df``.

    The single entry point every model in this package calls -
    individual ``add_*`` functions above exist so a caller can also
    compose a custom subset directly if a config-driven pass isn't the
    right fit.

    Args:
        df: A numeric frame indexed by a
            :class:`~pandas.DatetimeIndex`, oldest row first (e.g. as
            produced by :func:`app.ml.dataset_builder.DatasetBuilder.build`).
        config: Feature generation configuration. Defaults to
            :class:`FeatureConfig`'s defaults if omitted.

    Returns:
        A new :class:`pandas.DataFrame`: ``df``'s original columns
        plus every generated feature column, with leading rows
        containing window/lag-induced ``NaN`` dropped if
        ``config.dropna`` is ``True``.
    """
    config = config or FeatureConfig()
    numeric_columns = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    targets = config.target_columns or numeric_columns
    targets = [t for t in targets if t in df.columns]

    pieces: List[pd.DataFrame] = [df]

    for column in targets:
        for window in config.roll_windows:
            pieces.append(add_rolling_mean(df, column, window).to_frame())
            pieces.append(add_rolling_std(df, column, window).to_frame())
        if config.include_rate_of_change:
            pieces.append(add_rate_of_change(df, column).to_frame())
        if config.lag_counts > 0:
            pieces.append(add_lag_features(df, column, config.lag_counts))
        if config.include_change_features:
            pieces.append(add_change_feature(df, column).to_frame())

    if config.include_calendar_features:
        pieces.append(add_calendar_features(df))

    result = pd.concat(pieces, axis=1)
    # pct_change/diff can introduce +/-inf when a value is exactly
    # zero; treat those the same as NaN rather than letting an
    # estimator see an infinite feature value.
    result = result.replace([np.inf, -np.inf], np.nan)

    if config.dropna:
        result = result.dropna()

    logger.info(
        f"Feature engineering: {len(df.columns)} input column(s) -> "
        f"{len(result.columns)} feature column(s), {len(result)} row(s)"
    )
    return result


__all__ = [
    "FeatureConfig",
    "NAMED_CHANGE_FEATURES",
    "add_rolling_mean",
    "add_rolling_std",
    "add_rate_of_change",
    "add_lag_features",
    "add_change_feature",
    "add_calendar_features",
    "build_features",
]
