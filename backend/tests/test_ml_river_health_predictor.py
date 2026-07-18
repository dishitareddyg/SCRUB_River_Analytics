"""Unit tests for :mod:`app.ml.river_health_predictor`."""

from __future__ import annotations

import pytest

from app.ml.river_health_predictor import RiverHealthPredictor
from app.ml.utils import HealthCategory, categorize_health_score


def test_compute_score_ideal_conditions_near_100() -> None:
    predictor = RiverHealthPredictor()
    score = predictor.compute_score(
        {
            "dissolved_oxygen": 8.0,
            "ph_level": 7.0,
            "turbidity": 0.0,
            "conductivity": 300.0,
            "water_temperature": 18.0,
        }
    )
    assert score == pytest.approx(100.0, abs=0.5)


def test_compute_score_poor_conditions_is_low() -> None:
    predictor = RiverHealthPredictor()
    score = predictor.compute_score(
        {
            "dissolved_oxygen": 0.5,
            "ph_level": 3.0,
            "turbidity": 95.0,
            "conductivity": 5000.0,
            "water_temperature": 40.0,
        }
    )
    assert score < 20.0


def test_compute_score_missing_parameters_renormalizes() -> None:
    predictor = RiverHealthPredictor()
    score = predictor.compute_score({"dissolved_oxygen": 8.0})
    assert score == pytest.approx(100.0, abs=0.5)


def test_compute_score_no_scoreable_parameters_returns_none() -> None:
    predictor = RiverHealthPredictor()
    assert predictor.compute_score({}) is None
    assert predictor.compute_score({"unknown_param": 5.0}) is None


def test_categorize_health_score_thresholds() -> None:
    assert categorize_health_score(95.0) == HealthCategory.EXCELLENT
    assert categorize_health_score(90.0) == HealthCategory.EXCELLENT
    assert categorize_health_score(89.9) == HealthCategory.GOOD
    assert categorize_health_score(70.0) == HealthCategory.GOOD
    assert categorize_health_score(50.0) == HealthCategory.FAIR
    assert categorize_health_score(25.0) == HealthCategory.POOR
    assert categorize_health_score(10.0) == HealthCategory.CRITICAL


def test_forecast_requires_at_least_two_points() -> None:
    predictor = RiverHealthPredictor()
    assert predictor.forecast([], 3600.0) is None
    assert predictor.forecast([(0.0, 80.0)], 3600.0) is None


def test_forecast_increasing_trend() -> None:
    predictor = RiverHealthPredictor()
    history = [(float(i) * 3600.0, 50.0 + i) for i in range(10)]
    result = predictor.forecast(history, horizon_seconds=3600.0)
    assert result is not None
    assert result.predicted_score > result.current_score
    assert result.category == categorize_health_score(result.predicted_score)
    assert 0.0 <= result.confidence <= 1.0


def test_forecast_clamps_to_0_100_range() -> None:
    predictor = RiverHealthPredictor()
    history = [(float(i) * 3600.0, 95.0 + i * 2) for i in range(10)]
    result = predictor.forecast(history, horizon_seconds=36000.0)
    assert result is not None
    assert 0.0 <= result.predicted_score <= 100.0


def test_forecast_flat_history_predicts_same_score() -> None:
    predictor = RiverHealthPredictor()
    history = [(float(i) * 3600.0, 70.0) for i in range(10)]
    result = predictor.forecast(history, horizon_seconds=3600.0)
    assert result is not None
    assert result.predicted_score == pytest.approx(70.0, abs=0.5)
    assert result.confidence == pytest.approx(1.0, abs=0.05)
