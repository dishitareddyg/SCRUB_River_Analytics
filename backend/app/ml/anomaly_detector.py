"""Lightweight anomaly detection via Isolation Forest.

A single multivariate model over the current multi-sensor snapshot
(rather than one model per sensor) so it naturally captures
relationships *between* parameters (e.g. DO dropping while
conductivity rises together is more anomalous than either alone).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from app.utils.exceptions import ApplicationError
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: Number of top-deviating features reported as "contributing
#: parameters" for an anomalous point.
_TOP_CONTRIBUTORS = 3


class ModelNotFittedError(ApplicationError):
    """Raised when :meth:`AnomalyDetector.predict` is called before fitting."""


@dataclass(frozen=True)
class AnomalyPrediction:
    """One row's anomaly detection result.

    Attributes:
        anomaly_score: A ``0.0``-``1.0`` score, higher = more
            anomalous (inverted from scikit-learn's raw
            ``decision_function``, where higher normally means more
            normal, so this reads intuitively for API consumers).
        is_anomaly: ``True`` if classified as an anomaly.
        confidence: A ``0.0``-``1.0`` confidence in the label, based
            on how far the raw score sits from the decision boundary
            relative to the training score distribution.
        contributing_parameters: The features that deviate most (by
            absolute z-score against the training mean/std) from
            what the model considers typical, most-deviating first.
    """

    anomaly_score: float
    is_anomaly: bool
    confidence: float
    contributing_parameters: List[str]


class AnomalyDetector:
    """A fit/predict wrapper around :class:`~sklearn.ensemble.IsolationForest`.

    Attributes:
        contamination: Expected proportion of anomalous points in
            training data, forwarded to ``IsolationForest``.
        random_state: Random seed for reproducibility.
        n_estimators: Number of trees in the forest.
    """

    def __init__(self, contamination: float = 0.05, random_state: int = 42, n_estimators: int = 150) -> None:
        """Initialize an unfitted detector.

        Args:
            contamination: Expected proportion of anomalies, in
                ``(0, 0.5]``, forwarded to ``IsolationForest``.
            random_state: Random seed for reproducibility.
            n_estimators: Number of trees in the forest. Kept modest
                by default so training stays fast on a laptop.
        """
        self.contamination = contamination
        self.random_state = random_state
        self.n_estimators = n_estimators

        self._model: Optional[IsolationForest] = None
        self.feature_names_: List[str] = []
        self._train_mean: Optional[pd.Series] = None
        self._train_std: Optional[pd.Series] = None
        self._train_score_min: float = 0.0
        self._train_score_max: float = 1.0

    @property
    def is_fitted(self) -> bool:
        """Whether :meth:`fit` has been called successfully.

        Returns:
            ``True`` if the detector is ready for :meth:`predict`.
        """
        return self._model is not None

    def fit(self, df: pd.DataFrame) -> "AnomalyDetector":
        """Fit the Isolation Forest on a multi-parameter training frame.

        Args:
            df: A numeric, fully-populated (no ``NaN``) feature frame,
                one row per observation, one column per parameter/
                feature.

        Returns:
            ``self``, for chaining.

        Raises:
            ValueError: If ``df`` has fewer than 2 rows or no columns.
        """
        if df.empty or df.shape[1] == 0:
            raise ValueError("Cannot fit AnomalyDetector on an empty frame.")

        self.feature_names_ = list(df.columns)
        self._train_mean = df.mean()
        self._train_std = df.std().replace(0, 1.0)  # avoid divide-by-zero for constant columns

        self._model = IsolationForest(
            contamination=self.contamination,
            random_state=self.random_state,
            n_estimators=self.n_estimators,
        )
        self._model.fit(df[self.feature_names_])

        train_scores = self._model.decision_function(df[self.feature_names_])
        self._train_score_min = float(train_scores.min())
        self._train_score_max = float(train_scores.max())

        logger.info(f"AnomalyDetector fitted: features={self.feature_names_} rows={len(df)}")
        return self

    def predict_row(self, row: pd.Series) -> AnomalyPrediction:
        """Score a single observation.

        Args:
            row: A :class:`pandas.Series` containing at least every
                column in :attr:`feature_names_`.

        Returns:
            An :class:`AnomalyPrediction`.

        Raises:
            ModelNotFittedError: If called before :meth:`fit`.
        """
        if not self.is_fitted:
            raise ModelNotFittedError("AnomalyDetector.predict_row() called before fit().")

        ordered = row[self.feature_names_].to_frame().T.astype(float)
        raw_score = float(self._model.decision_function(ordered)[0])
        label = int(self._model.predict(ordered)[0])  # 1 = normal, -1 = anomaly

        # Invert + min-max normalize against the training distribution
        # so the reported score reads as "higher = more anomalous",
        # 0-1, regardless of IsolationForest's internal score scale.
        score_range = max(self._train_score_max - self._train_score_min, 1e-9)
        normalized_normalcy = (raw_score - self._train_score_min) / score_range
        anomaly_score = float(np.clip(1.0 - normalized_normalcy, 0.0, 1.0))

        # Confidence: distance from the 0.5 decision midpoint, scaled
        # to 0-1 - a score near either extreme is a confident call, a
        # score near the middle is a borderline one.
        confidence = float(np.clip(abs(anomaly_score - 0.5) * 2.0, 0.0, 1.0))

        z_scores = ((row[self.feature_names_] - self._train_mean) / self._train_std).abs()
        contributors = z_scores.sort_values(ascending=False).head(_TOP_CONTRIBUTORS)
        contributing_parameters = [name for name in contributors.index if contributors[name] > 1.0]

        return AnomalyPrediction(
            anomaly_score=round(anomaly_score, 4),
            is_anomaly=label == -1,
            confidence=round(confidence, 4),
            contributing_parameters=contributing_parameters,
        )

    def evaluate(self, df: pd.DataFrame, labels: Sequence[int]) -> dict:
        """Evaluate precision/recall against known anomaly labels, if available.

        Args:
            df: A feature frame matching :attr:`feature_names_`.
            labels: Ground-truth binary labels (``1`` = anomaly,
                ``0`` = normal), aligned row-for-row with ``df``.

        Returns:
            A dict with keys ``"precision"`` and ``"recall"`` (``0.0``
            if there are fewer than 2 rows or no positive labels).

        Raises:
            ModelNotFittedError: If called before :meth:`fit`.
        """
        if not self.is_fitted:
            raise ModelNotFittedError("AnomalyDetector.evaluate() called before fit().")

        from app.ml.utils import classification_metrics

        raw_predictions = self._model.predict(df[self.feature_names_])
        predicted = [1 if p == -1 else 0 for p in raw_predictions]
        return classification_metrics(np.array(labels), np.array(predicted))


__all__ = ["AnomalyDetector", "AnomalyPrediction", "ModelNotFittedError"]
