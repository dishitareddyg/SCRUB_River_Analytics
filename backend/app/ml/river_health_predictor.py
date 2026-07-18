"""Composite River Health Score computation and forecast.

The composite score computed here is a lightweight, this-module-only
indicator built for *forecasting purposes* - it is intentionally not
presented as an authoritative Water Quality Index (WQI computation was
explicitly out of scope for earlier modules, and remains so here);
this predictor only needs a single numeric health signal it can
project forward in time.

The forecast itself reuses
:func:`app.historical.trends.linear_trend` (the same ordinary-least-
squares method Module 6 uses for parameter trend detection) rather
than re-implementing regression here, applied to a short history of
this module's own composite score instead of a raw sensor value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from app.historical.trends import linear_trend, trend_confidence
from app.ml.utils import HealthCategory, categorize_health_score, clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class SubIndexWeight:
    """A sub-index's contribution weight to the composite score.

    Attributes:
        parameter: The feature-snapshot field this sub-index reads.
        weight: Contribution weight (all weights should sum to 1.0
            across :data:`DEFAULT_WEIGHTS`).
    """

    parameter: str
    weight: float


#: Sub-index weights for the composite score. Chosen to emphasize
#: dissolved oxygen (the single strongest general-purpose river health
#: signal) while still reflecting pH, turbidity, conductivity, and
#: temperature.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "dissolved_oxygen": 0.30,
    "ph_level": 0.20,
    "turbidity": 0.20,
    "conductivity": 0.15,
    "water_temperature": 0.15,
}


def _do_sub_score(mg_per_l: float) -> float:
    """Score dissolved oxygen: 100 at/above 8 mg/L, 0 at 0 mg/L, linear between."""
    return clamp((mg_per_l / 8.0) * 100.0, 0.0, 100.0)


def _ph_sub_score(ph: float) -> float:
    """Score pH: 100 at neutral (7.0), degrading to 0 by 3.5 units away."""
    distance = abs(ph - 7.0)
    return clamp(100.0 - (distance / 3.5) * 100.0, 0.0, 100.0)


def _turbidity_sub_score(ntu: float) -> float:
    """Score turbidity: 100 at 0 NTU, degrading to 0 at 100 NTU."""
    return clamp(100.0 - (ntu / 100.0) * 100.0, 0.0, 100.0)


def _conductivity_sub_score(us_per_cm: float) -> float:
    """Score conductivity: 100 within a typical freshwater band (150-500 µS/cm), degrading outside it."""
    if 150.0 <= us_per_cm <= 500.0:
        return 100.0
    distance = (150.0 - us_per_cm) if us_per_cm < 150.0 else (us_per_cm - 500.0)
    return clamp(100.0 - (distance / 500.0) * 100.0, 0.0, 100.0)


def _temperature_sub_score(celsius: float) -> float:
    """Score water temperature: 100 within 10-25°C, degrading outside it."""
    if 10.0 <= celsius <= 25.0:
        return 100.0
    distance = (10.0 - celsius) if celsius < 10.0 else (celsius - 25.0)
    return clamp(100.0 - (distance / 15.0) * 100.0, 0.0, 100.0)


_SUB_SCORE_FUNCTIONS = {
    "dissolved_oxygen": _do_sub_score,
    "ph_level": _ph_sub_score,
    "turbidity": _turbidity_sub_score,
    "conductivity": _conductivity_sub_score,
    "water_temperature": _temperature_sub_score,
}


@dataclass(frozen=True)
class HealthForecastResult:
    """The result of :meth:`RiverHealthPredictor.forecast`.

    Attributes:
        current_score: The composite score at the most recent
            observation.
        predicted_score: The forecast composite score at the
            requested horizon.
        category: The :class:`~app.ml.utils.HealthCategory` of
            ``predicted_score``.
        confidence: A ``0.0``-``1.0`` confidence, derived from the
            forecast trend line's fit quality.
    """

    current_score: float
    predicted_score: float
    category: HealthCategory
    confidence: float


class RiverHealthPredictor:
    """Computes the composite River Health Score and its short-horizon forecast.

    Attributes:
        weights: Parameter -> sub-index contribution weight. Any
            parameter missing from a given snapshot is excluded and
            the remaining weights are renormalized, so the score stays
            meaningful even with a partial sensor set.
    """

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        """Initialize the predictor.

        Args:
            weights: Custom sub-index weights. Defaults to
                :data:`DEFAULT_WEIGHTS`.
        """
        self.weights = weights or DEFAULT_WEIGHTS

    def compute_score(self, readings: Dict[str, Optional[float]]) -> Optional[float]:
        """Compute the composite 0-100 River Health Score for one snapshot.

        Args:
            readings: Parameter -> current value (any subset of
                :data:`DEFAULT_WEIGHTS`'s keys; missing/``None`` values
                are excluded rather than treated as zero).

        Returns:
            The weighted composite score in ``[0, 100]``, or ``None``
            if no scoreable parameter is present.
        """
        weighted_sum = 0.0
        weight_total = 0.0

        for parameter, weight in self.weights.items():
            value = readings.get(parameter)
            if value is None:
                continue
            sub_score_fn = _SUB_SCORE_FUNCTIONS.get(parameter)
            if sub_score_fn is None:
                continue
            weighted_sum += sub_score_fn(float(value)) * weight
            weight_total += weight

        if weight_total == 0.0:
            return None
        return round(clamp(weighted_sum / weight_total, 0.0, 100.0), 2)

    def forecast(
        self, score_history: Sequence[Tuple[float, float]], horizon_seconds: float
    ) -> Optional[HealthForecastResult]:
        """Forecast the composite score ``horizon_seconds`` past the last observation.

        Args:
            score_history: ``(elapsed_seconds, score)`` pairs,
                chronologically ordered, where ``elapsed_seconds`` is
                seconds since the first observation (matching the
                convention :meth:`app.historical.service.HistoricalAnalyticsService.get_trends`
                uses internally).
            horizon_seconds: How far past the *last* observation's
                ``elapsed_seconds`` to forecast, in seconds.

        Returns:
            A :class:`HealthForecastResult`, or ``None`` if fewer than
            2 historical points are available (a trend line needs at
            least 2 points).
        """
        if len(score_history) < 2:
            return None

        fitted = linear_trend(list(score_history))
        if fitted is None:
            return None

        last_elapsed, current_score = score_history[-1]
        predicted_raw = fitted.slope * (last_elapsed + horizon_seconds) + fitted.intercept
        predicted_score = round(clamp(predicted_raw, 0.0, 100.0), 2)
        confidence = trend_confidence(fitted) or 0.0

        result = HealthForecastResult(
            current_score=round(current_score, 2),
            predicted_score=predicted_score,
            category=categorize_health_score(predicted_score),
            confidence=round(confidence, 4),
        )
        logger.info(
            f"River health forecast: current={result.current_score} predicted={result.predicted_score} "
            f"category={result.category.value} confidence={result.confidence}"
        )
        return result


__all__ = ["RiverHealthPredictor", "HealthForecastResult", "DEFAULT_WEIGHTS", "SubIndexWeight"]
