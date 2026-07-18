"""Turn historical database records into an ML-ready pandas DataFrame.

Deliberately built *on top of* :mod:`app.historical` rather than
re-querying :class:`~app.database.service.DatabaseService` directly:
:func:`app.historical.utils.fetch_parameter_series` already resolves a
"parameter" (raw sensor **or** derived analytics key) to its in-range
``(timestamp, value)`` points, page-limits/caps the fetch, and handles
missing values - reusing it means this module never re-implements
that (per this project's "No Duplicate Logic" standard) and stays in
lockstep with Module 6 if that resolution logic ever changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Literal, Optional, Sequence, Tuple

import pandas as pd

from app.analytics.config import AnalyticsConfig
from app.database.service import DatabaseService
from app.historical.utils import fetch_parameter_series
from app.serial.sensor_registry import SensorRegistry
from app.utils.exceptions import BadRequestError
from app.utils.logger import get_logger

logger = get_logger(__name__)

FillMethod = Literal["interpolate", "ffill", "drop"]
OutlierMethod = Literal["iqr", "zscore", "none"]
NormalizeMethod = Literal["standard", "minmax", "none"]


@dataclass
class DatasetBuildResult:
    """The output of :meth:`DatasetBuilder.build`.

    Attributes:
        frame: The assembled, cleaned :class:`pandas.DataFrame`,
            indexed by a UTC :class:`~pandas.DatetimeIndex`, one
            column per requested parameter.
        parameters: The parameter keys included, in column order.
        display_names: Parameter key -> human friendly display name.
        units: Parameter key -> unit of measurement (``None`` if
            unknown).
        start: Start of the requested time range.
        end: End of the requested time range.
        resample_frequency: The pandas offset alias used to align all
            parameters onto a shared time axis (e.g. ``"1h"``).
        dropped_rows: Number of rows dropped by missing-value handling
            (only when ``fill_method="drop"``).
    """

    frame: pd.DataFrame
    parameters: List[str]
    display_names: Dict[str, str]
    units: Dict[str, Optional[str]]
    start: datetime
    end: datetime
    resample_frequency: str
    dropped_rows: int = 0


class DatasetBuilder:
    """Builds ML-ready datasets from historical sensor/analytics data.

    Every dependency is injected through the constructor, matching
    every other service in this codebase (Dependency Injection coding
    standard) - see :class:`app.historical.service.HistoricalAnalyticsService`
    for the identical pattern this class follows.

    Attributes:
        db: The injected database facade.
        sensor_registry: The injected configured sensor registry.
        analytics_config: The injected Analytics Engine configuration.
    """

    def __init__(
        self,
        db: DatabaseService,
        sensor_registry: SensorRegistry,
        analytics_config: AnalyticsConfig,
    ) -> None:
        """Initialize the builder.

        Args:
            db: The database facade.
            sensor_registry: The configured sensor registry.
            analytics_config: The Analytics Engine configuration
                (needed to recompute derived-parameter history).
        """
        self.db = db
        self.sensor_registry = sensor_registry
        self.analytics_config = analytics_config

    # ------------------------------------------------------------------
    # Fetch + assemble
    # ------------------------------------------------------------------

    def _fetch_series(
        self, parameter: str, start: datetime, end: datetime, device_name: Optional[str]
    ) -> Tuple[pd.Series, str, Optional[str]]:
        """Fetch one parameter's points and resample them onto a Series.

        Args:
            parameter: A sensor or analytics parameter key.
            start: Inclusive range start.
            end: Inclusive range end.
            device_name: Optional device filter.

        Returns:
            A ``(series, display_name, unit)`` tuple. ``series`` is
            indexed by raw (un-resampled) reading timestamps.

        Raises:
            NotFoundError: If ``parameter`` is unknown (propagated
                from :func:`app.historical.utils.fetch_parameter_series`).
        """
        result = fetch_parameter_series(
            self.db, self.sensor_registry, self.analytics_config, parameter, start, end, device_name
        )
        if result.points:
            index = pd.DatetimeIndex([ts for ts, _ in result.points], name="timestamp")
            series = pd.Series([v for _, v in result.points], index=index, name=parameter)
        else:
            series = pd.Series([], index=pd.DatetimeIndex([], name="timestamp"), name=parameter, dtype=float)
        return series, result.display_name, result.unit

    def build(
        self,
        parameters: Sequence[str],
        start: datetime,
        end: datetime,
        device_name: Optional[str] = None,
        resample_frequency: str = "1h",
        fill_method: FillMethod = "interpolate",
        outlier_method: OutlierMethod = "iqr",
        outlier_factor: float = 3.0,
    ) -> DatasetBuildResult:
        """Assemble a multi-parameter, time-aligned ML-ready dataset.

        Each parameter is fetched independently (raw sensor or
        analytics, resolved the same way as every historical
        endpoint), resampled onto a shared ``resample_frequency`` time
        axis via the mean of each bucket, then joined into one frame.

        Args:
            parameters: Sensor and/or analytics parameter keys to
                include as columns.
            start: Inclusive range start.
            end: Inclusive range end.
            device_name: Optional device filter, applied to every
                parameter.
            resample_frequency: A pandas offset alias (e.g. ``"1h"``,
                ``"15min"``) all parameters are aligned onto.
            fill_method: How to handle resampling gaps/missing values:
                ``"interpolate"`` (linear time interpolation, then
                forward/back-fill any still-missing edges),
                ``"ffill"`` (forward-fill only), or ``"drop"`` (drop
                any row with a missing value in any column).
            outlier_method: ``"iqr"`` (clip values outside
                ``outlier_factor`` * IQR from the nearest quartile),
                ``"zscore"`` (clip values beyond ``outlier_factor``
                standard deviations from the mean), or ``"none"``.
            outlier_factor: The IQR multiplier or z-score threshold
                used by ``outlier_method``.

        Returns:
            A populated :class:`DatasetBuildResult`.

        Raises:
            BadRequestError: If ``parameters`` is empty.
            NotFoundError: If any parameter key is unknown.
        """
        if not parameters:
            raise BadRequestError("At least one parameter is required to build a dataset.")

        columns: Dict[str, pd.Series] = {}
        display_names: Dict[str, str] = {}
        units: Dict[str, Optional[str]] = {}

        for parameter in parameters:
            series, display_name, unit = self._fetch_series(parameter, start, end, device_name)
            resampled = series.resample(resample_frequency).mean() if not series.empty else series
            columns[parameter] = resampled
            display_names[parameter] = display_name
            units[parameter] = unit

        frame = pd.DataFrame(columns)
        # Ensure a complete, gap-free time axis across the full
        # requested range even if every parameter's raw data is sparse
        # near the edges - downstream feature engineering (rolling/lag
        # windows) needs an evenly spaced index to be meaningful.
        if not frame.empty:
            full_index = pd.date_range(start=frame.index.min(), end=frame.index.max(), freq=resample_frequency)
            frame = frame.reindex(full_index)

        frame = self.handle_outliers(frame, method=outlier_method, factor=outlier_factor)
        frame, dropped = self.handle_missing_values(frame, method=fill_method)

        empty_columns = [c for c in frame.columns if frame[c].isna().all()]
        if empty_columns:
            logger.warning(
                f"Dropping parameter(s) with no usable data in range: {empty_columns} "
                f"(start={start.isoformat()} end={end.isoformat()})"
            )
            frame = frame.drop(columns=empty_columns)

        logger.info(
            f"Dataset built: parameters={list(parameters)} rows={len(frame)} "
            f"freq={resample_frequency} dropped_rows={dropped}"
        )
        return DatasetBuildResult(
            frame=frame,
            parameters=list(parameters),
            display_names=display_names,
            units=units,
            start=start,
            end=end,
            resample_frequency=resample_frequency,
            dropped_rows=dropped,
        )

    # ------------------------------------------------------------------
    # Cleaning
    # ------------------------------------------------------------------

    @staticmethod
    def handle_missing_values(df: pd.DataFrame, method: FillMethod = "interpolate") -> Tuple[pd.DataFrame, int]:
        """Fill or drop missing values in a resampled dataset.

        Args:
            df: The (possibly gappy) resampled frame.
            method: ``"interpolate"`` (time-based linear
                interpolation, then edge-fill any still-missing
                leading/trailing values), ``"ffill"`` (forward-fill
                only, leaving any leading gap as-is), or ``"drop"``
                (drop rows containing any missing value).

        Returns:
            A ``(cleaned_frame, dropped_row_count)`` tuple.
        """
        if df.empty:
            return df, 0

        if method == "drop":
            before = len(df)
            cleaned = df.dropna(how="any")
            return cleaned, before - len(cleaned)

        if method == "ffill":
            return df.ffill(), 0

        # "interpolate"
        cleaned = df.interpolate(method="time", limit_direction="both")
        cleaned = cleaned.ffill().bfill()
        return cleaned, 0

    @staticmethod
    def handle_outliers(df: pd.DataFrame, method: OutlierMethod = "iqr", factor: float = 3.0) -> pd.DataFrame:
        """Clip (not drop) statistical outliers per column.

        Clipping rather than dropping keeps the time axis intact,
        which matters for rolling/lag feature generation downstream.

        Args:
            df: The source frame.
            method: ``"iqr"`` (clip outside ``factor`` * IQR from the
                nearest quartile), ``"zscore"`` (clip beyond ``factor``
                standard deviations from the mean), or ``"none"``
                (no-op).
            factor: The IQR multiplier or z-score threshold.

        Returns:
            A new frame with outliers clipped; unchanged if ``method``
            is ``"none"`` or ``df`` is empty.
        """
        if method == "none" or df.empty:
            return df

        result = df.copy()
        for column in result.columns:
            series = result[column]
            if method == "iqr":
                q1, q3 = series.quantile(0.25), series.quantile(0.75)
                iqr = q3 - q1
                if iqr == 0 or pd.isna(iqr):
                    continue
                lower, upper = q1 - factor * iqr, q3 + factor * iqr
            else:  # zscore
                mean, std = series.mean(), series.std()
                if not std or pd.isna(std):
                    continue
                lower, upper = mean - factor * std, mean + factor * std
            result[column] = series.clip(lower=lower, upper=upper)
        return result

    @staticmethod
    def normalize(
        df: pd.DataFrame, columns: Optional[Sequence[str]] = None, method: NormalizeMethod = "standard"
    ) -> Tuple[pd.DataFrame, Optional[object]]:
        """Normalize selected columns, returning the fitted scaler.

        Returning the scaler (rather than only the transformed frame)
        lets a caller persist it alongside a trained model (via
        :mod:`app.ml.model_manager`) so future inference inputs can be
        transformed identically.

        Args:
            df: The source frame.
            columns: Columns to normalize. Defaults to every column.
            method: ``"standard"`` (zero mean, unit variance via
                :class:`~sklearn.preprocessing.StandardScaler`),
                ``"minmax"`` (0-1 range via
                :class:`~sklearn.preprocessing.MinMaxScaler`), or
                ``"none"`` (no-op, returns ``df`` unchanged and
                ``None`` for the scaler).

        Returns:
            A ``(normalized_frame, fitted_scaler_or_none)`` tuple.
        """
        if method == "none" or df.empty:
            return df, None

        from sklearn.preprocessing import MinMaxScaler, StandardScaler

        target_columns = list(columns) if columns is not None else list(df.columns)
        scaler = StandardScaler() if method == "standard" else MinMaxScaler()

        result = df.copy()
        result[target_columns] = scaler.fit_transform(result[target_columns])
        return result, scaler


__all__ = ["DatasetBuilder", "DatasetBuildResult", "FillMethod", "OutlierMethod", "NormalizeMethod"]
