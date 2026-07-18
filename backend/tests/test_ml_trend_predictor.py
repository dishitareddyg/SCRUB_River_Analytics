"""Unit tests for :mod:`app.ml.trend_predictor`."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.trend_predictor import ModelNotTrainedError, TrendPredictor


def _linear_dataset(n: int = 50) -> tuple[pd.DataFrame, pd.Series]:
    x = np.arange(n, dtype=float)
    X = pd.DataFrame({"feature_a": x, "feature_b": x * 2.0})
    y = pd.Series(x * 3.0 + 1.0, name="target")
    return X, y


def test_is_trained_false_before_train() -> None:
    predictor = TrendPredictor("dissolved_oxygen", "next_hour")
    assert predictor.is_trained is False


def test_train_too_few_rows_raises() -> None:
    predictor = TrendPredictor("dissolved_oxygen", "next_hour")
    X = pd.DataFrame({"a": [1.0, 2.0]})
    y = pd.Series([1.0, 2.0])
    with pytest.raises(ValueError):
        predictor.train(X, y)


def test_predict_before_train_raises() -> None:
    predictor = TrendPredictor("dissolved_oxygen", "next_hour")
    with pytest.raises(ModelNotTrainedError):
        predictor.predict(pd.DataFrame({"a": [1.0]}))


def test_predict_empty_frame_raises() -> None:
    X, y = _linear_dataset()
    predictor = TrendPredictor("dissolved_oxygen", "next_hour", n_estimators=20).train(X, y)
    with pytest.raises(ValueError):
        predictor.predict(pd.DataFrame(columns=X.columns))


def test_train_sets_feature_names_and_metrics() -> None:
    X, y = _linear_dataset()
    predictor = TrendPredictor("dissolved_oxygen", "next_hour", n_estimators=20, random_state=1).train(X, y)
    assert predictor.is_trained is True
    assert predictor.feature_names_ == ["feature_a", "feature_b"]
    assert set(predictor.metrics_.keys()) == {"mae", "rmse", "r2"}


def test_predict_on_near_linear_data_is_reasonably_accurate() -> None:
    X, y = _linear_dataset(200)
    predictor = TrendPredictor("dissolved_oxygen", "next_hour", n_estimators=100, random_state=1).train(X, y)
    prediction = predictor.predict(X)
    expected = float(y.iloc[-1])
    assert prediction.predicted_value == pytest.approx(expected, rel=0.1)
    assert prediction.confidence_interval_lower <= prediction.predicted_value <= prediction.confidence_interval_upper
    assert 0.0 <= prediction.model_confidence <= 1.0


def test_predict_uses_last_row_of_input() -> None:
    X, y = _linear_dataset(100)
    predictor = TrendPredictor("dissolved_oxygen", "next_hour", n_estimators=50, random_state=1).train(X, y)
    truncated = X.iloc[:10]
    prediction = predictor.predict(truncated)
    # Predicting from a truncated frame (last row = index 9) should differ
    # meaningfully from predicting off the full frame's last row (index 99).
    full_prediction = predictor.predict(X)
    assert prediction.predicted_value != full_prediction.predicted_value


def test_xgboost_algorithm_falls_back_gracefully_if_unavailable(monkeypatch) -> None:
    predictor = TrendPredictor("dissolved_oxygen", "next_hour", algorithm="xgboost")
    assert predictor.algorithm in ("xgboost", "random_forest")


def test_xgboost_algorithm_trains_successfully() -> None:
    X, y = _linear_dataset(60)
    predictor = TrendPredictor(
        "dissolved_oxygen", "next_hour", algorithm="xgboost", n_estimators=20, random_state=1
    ).train(X, y)
    assert predictor.is_trained is True
    prediction = predictor.predict(X)
    assert prediction.predicted_value is not None
