"""Shared constants, enums, and small metric helpers for ``app.ml``.

Kept dependency-light (``numpy``/``sklearn.metrics`` only) so every
other submodule can import from here without pulling in the database
or API layers.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from app.utils.exceptions import ApplicationError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class InsufficientDataError(ApplicationError):
    """Raised internally when too little historical data exists to train/serve a model.

    Always caught within :mod:`app.ml.inference` and translated into
    an :attr:`MLStatus.INSUFFICIENT_DATA` response - never propagated
    to the API layer as an HTTP error.
    """

    status_code = 200


class MLStatus(str, Enum):
    """The outcome of an on-demand ML inference call.

    Attributes:
        OK: A prediction was produced.
        INSUFFICIENT_DATA: Fewer than
            ``Settings.ml_min_training_samples`` usable historical
            points were available to train or reuse a model - no
            value is fabricated from too little data.
        ERROR: An unexpected failure occurred while training or
            predicting; details are logged, never raised past the
            inference façade.
    """

    OK = "ok"
    INSUFFICIENT_DATA = "insufficient_data"
    ERROR = "error"


class PredictionHorizon(str, Enum):
    """A supported trend-prediction / forecast horizon.

    Attributes:
        NEXT_HOUR: One resampling step ahead (see
            ``Settings.ml_resample_frequency``, default hourly).
        NEXT_DAY: 24 hourly steps ahead.
        NEXT_WEEK: 168 hourly steps ahead.
    """

    NEXT_HOUR = "next_hour"
    NEXT_DAY = "next_day"
    NEXT_WEEK = "next_week"


#: Number of ``Settings.ml_resample_frequency`` steps each horizon
#: looks ahead, assuming the default hourly resampling frequency.
HORIZON_STEPS: Dict[PredictionHorizon, int] = {
    PredictionHorizon.NEXT_HOUR: 1,
    PredictionHorizon.NEXT_DAY: 24,
    PredictionHorizon.NEXT_WEEK: 24 * 7,
}

#: Parameters supported by trend prediction out of the box (per this
#: module's requirements) - sensor keys where noted, otherwise
#: registered analytics parameter keys (see app/config/sensors.yaml
#: and app/analytics/*).
DEFAULT_TREND_PARAMETERS: List[str] = [
    "dissolved_oxygen",
    "ph_level",
    "conductivity",
    "water_temperature",
    "water_level",
    "river_discharge",
]

#: Sensor/analytics parameters read for anomaly detection's
#: multi-sensor snapshot and for pollution-source rule evaluation.
DEFAULT_MONITORING_PARAMETERS: List[str] = [
    "dissolved_oxygen",
    "ph_level",
    "conductivity",
    "turbidity",
    "orp",
    "water_temperature",
    "water_level",
    "rainfall",
]


class PollutionSource(str, Enum):
    """A candidate pollution source class (see ``pollution_classifier.py``).

    Attributes:
        DOMESTIC_SEWAGE: Untreated/poorly treated wastewater signature
            (low DO, elevated conductivity/turbidity, low ORP).
        AGRICULTURAL_RUNOFF: Fertilizer/soil runoff signature
            (turbidity and conductivity rise following rainfall).
        INDUSTRIAL_EFFLUENT: Chemical discharge signature (sharp
            conductivity/pH/ORP deviation with little turbidity
            change).
        STORMWATER: Short-lived rainfall-driven turbidity/flow spike.
        NATURAL_VARIATION: Deviations fully explained by normal
            seasonal/diurnal variation.
        UNKNOWN: No rule triggered with meaningful confidence.
    """

    DOMESTIC_SEWAGE = "domestic_sewage"
    AGRICULTURAL_RUNOFF = "agricultural_runoff"
    INDUSTRIAL_EFFLUENT = "industrial_effluent"
    STORMWATER = "stormwater"
    NATURAL_VARIATION = "natural_variation"
    UNKNOWN = "unknown"


class HealthCategory(str, Enum):
    """A qualitative band for the composite River Health Score (0-100).

    Attributes:
        EXCELLENT: Score >= 90.
        GOOD: 70 <= score < 90.
        FAIR: 50 <= score < 70.
        POOR: 25 <= score < 50.
        CRITICAL: Score < 25.
    """

    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"


#: Ascending score thresholds mapped to the category whose lower bound
#: they represent. Evaluated top-down in :func:`categorize_health_score`.
_HEALTH_THRESHOLDS = [
    (90.0, HealthCategory.EXCELLENT),
    (70.0, HealthCategory.GOOD),
    (50.0, HealthCategory.FAIR),
    (25.0, HealthCategory.POOR),
]


def categorize_health_score(score: float) -> HealthCategory:
    """Map a 0-100 composite health score to a :class:`HealthCategory`.

    Args:
        score: A River Health Score, expected in ``[0, 100]`` (values
            outside that range are clamped by the caller upstream;
            this function only compares thresholds).

    Returns:
        The matching :class:`HealthCategory`.
    """
    for threshold, category in _HEALTH_THRESHOLDS:
        if score >= threshold:
            return category
    return HealthCategory.CRITICAL


def clamp(value: float, low: float, high: float) -> float:
    """Clamp ``value`` into ``[low, high]``.

    Args:
        value: The value to clamp.
        low: Lower bound.
        high: Upper bound.

    Returns:
        ``value`` restricted to ``[low, high]``.
    """
    return max(low, min(high, value))


def confidence_from_r2(r2: float) -> float:
    """Convert an R² score into a ``0.0``-``1.0`` model-confidence value.

    R² can be arbitrarily negative for a poorly fit model (worse than
    predicting the mean); this clamps that down to ``0.0`` rather than
    reporting a negative confidence.

    Args:
        r2: The coefficient of determination on a holdout set.

    Returns:
        ``r2`` clamped to ``[0.0, 1.0]``.
    """
    return clamp(float(r2), 0.0, 1.0)


def regression_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Compute MAE, RMSE, and R² for a regression holdout evaluation.

    Args:
        y_true: Ground-truth values.
        y_pred: Predicted values, aligned with ``y_true``.

    Returns:
        A dict with keys ``"mae"``, ``"rmse"``, and ``"r2"``. All
        ``0.0`` if fewer than 2 samples are given (a holdout of that
        size can't support these metrics meaningfully).
    """
    if len(y_true) < 2:
        return {"mae": 0.0, "rmse": 0.0, "r2": 0.0}
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    r2 = float(r2_score(y_true, y_pred))
    return {"mae": mae, "rmse": rmse, "r2": r2}


def classification_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> Dict[str, float]:
    """Compute precision/recall for a binary anomaly-detection holdout.

    Args:
        y_true: Ground-truth binary labels (``1`` = anomaly, ``0`` =
            normal).
        y_pred: Predicted binary labels, aligned with ``y_true``.

    Returns:
        A dict with keys ``"precision"`` and ``"recall"``, ``0.0`` if
        fewer than 2 samples or no positive class is present in
        ``y_true`` (precision/recall are undefined without any
        positives to evaluate against).
    """
    from sklearn.metrics import precision_score, recall_score

    if len(y_true) < 2 or sum(y_true) == 0:
        return {"precision": 0.0, "recall": 0.0}
    precision = float(precision_score(y_true, y_pred, zero_division=0))
    recall = float(recall_score(y_true, y_pred, zero_division=0))
    return {"precision": precision, "recall": recall}


def horizon_to_seconds(horizon: PredictionHorizon, resample_frequency: str) -> float:
    """Convert a prediction horizon into seconds, given the resampling step size.

    Args:
        horizon: The requested forecast horizon.
        resample_frequency: A pandas offset alias (e.g. ``"1h"``) -
            the time represented by one row in a resampled dataset.

    Returns:
        The horizon expressed in seconds (``HORIZON_STEPS[horizon]``
        multiplied by the resampling step's duration).
    """
    step_seconds = pd.Timedelta(resample_frequency).total_seconds()
    return HORIZON_STEPS[horizon] * step_seconds


__all__ = [
    "MLStatus",
    "PredictionHorizon",
    "HORIZON_STEPS",
    "DEFAULT_TREND_PARAMETERS",
    "DEFAULT_MONITORING_PARAMETERS",
    "PollutionSource",
    "HealthCategory",
    "InsufficientDataError",
    "categorize_health_score",
    "clamp",
    "confidence_from_r2",
    "regression_metrics",
    "classification_metrics",
    "horizon_to_seconds",
]
