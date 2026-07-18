"""Unit tests for :mod:`app.ml.anomaly_detector`."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.ml.anomaly_detector import AnomalyDetector, ModelNotFittedError


def _normal_training_frame(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "dissolved_oxygen": rng.normal(7.5, 0.3, n),
            "conductivity": rng.normal(300.0, 15.0, n),
        }
    )


def test_is_fitted_false_before_fit() -> None:
    detector = AnomalyDetector()
    assert detector.is_fitted is False


def test_fit_on_empty_frame_raises() -> None:
    detector = AnomalyDetector()
    with pytest.raises(ValueError):
        detector.fit(pd.DataFrame())


def test_predict_row_before_fit_raises() -> None:
    detector = AnomalyDetector()
    with pytest.raises(ModelNotFittedError):
        detector.predict_row(pd.Series({"dissolved_oxygen": 7.5, "conductivity": 300.0}))


def test_fit_sets_feature_names_and_is_fitted() -> None:
    detector = AnomalyDetector(random_state=1).fit(_normal_training_frame())
    assert detector.is_fitted is True
    assert set(detector.feature_names_) == {"dissolved_oxygen", "conductivity"}


def test_predict_row_normal_point_has_low_anomaly_score() -> None:
    detector = AnomalyDetector(contamination=0.05, random_state=1).fit(_normal_training_frame())
    normal_point = pd.Series({"dissolved_oxygen": 7.5, "conductivity": 300.0})
    prediction = detector.predict_row(normal_point)
    assert 0.0 <= prediction.anomaly_score <= 1.0
    assert prediction.is_anomaly is False


def test_predict_row_extreme_point_flagged_as_anomaly() -> None:
    detector = AnomalyDetector(contamination=0.05, random_state=1).fit(_normal_training_frame())
    extreme_point = pd.Series({"dissolved_oxygen": 0.1, "conductivity": 5000.0})
    prediction = detector.predict_row(extreme_point)
    assert prediction.is_anomaly is True
    assert prediction.anomaly_score > 0.5
    assert "conductivity" in prediction.contributing_parameters or "dissolved_oxygen" in prediction.contributing_parameters


def test_predict_row_confidence_is_bounded() -> None:
    detector = AnomalyDetector(random_state=1).fit(_normal_training_frame())
    prediction = detector.predict_row(pd.Series({"dissolved_oxygen": 7.5, "conductivity": 300.0}))
    assert 0.0 <= prediction.confidence <= 1.0


def test_evaluate_before_fit_raises() -> None:
    detector = AnomalyDetector()
    with pytest.raises(ModelNotFittedError):
        detector.evaluate(_normal_training_frame(10), [0] * 10)


def test_evaluate_returns_precision_and_recall() -> None:
    train = _normal_training_frame(200)
    detector = AnomalyDetector(contamination=0.05, random_state=1).fit(train)
    eval_frame = pd.concat(
        [train, pd.DataFrame({"dissolved_oxygen": [0.0] * 10, "conductivity": [9000.0] * 10})],
        ignore_index=True,
    )
    labels = [0] * 200 + [1] * 10
    metrics = detector.evaluate(eval_frame, labels)
    assert "precision" in metrics
    assert "recall" in metrics
    assert 0.0 <= metrics["precision"] <= 1.0
    assert 0.0 <= metrics["recall"] <= 1.0
