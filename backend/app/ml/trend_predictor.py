"""Trend prediction via Random Forest or XGBoost regression.

Classical, CPU-only ensemble regressors only - no deep learning. A
confidence interval is derived from the spread across the forest's
individual trees rather than a separate quantile model, keeping this
lightweight enough to train and predict on a laptop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Literal

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from app.ml.utils import confidence_from_r2, regression_metrics
from app.utils.exceptions import ApplicationError
from app.utils.logger import get_logger

logger = get_logger(__name__)

Algorithm = Literal["random_forest", "xgboost"]

#: Z-score for a ~95% confidence interval around the ensemble's mean
#: prediction, treating the per-tree prediction spread as
#: approximately normal.
_CI_Z_SCORE = 1.96

#: Fraction of (chronologically ordered) rows held out for evaluation.
_HOLDOUT_FRACTION = 0.2


class ModelNotTrainedError(ApplicationError):
    """Raised when :meth:`TrendPredictor.predict` is called before training."""


@dataclass(frozen=True)
class TrendPrediction:
    """One prediction from a trained :class:`TrendPredictor`.

    Attributes:
        predicted_value: The forecast value.
        confidence_interval_lower: Lower bound of an approximate 95%
            confidence interval.
        confidence_interval_upper: Upper bound of an approximate 95%
            confidence interval.
        model_confidence: A ``0.0``-``1.0`` confidence score derived
            from the model's holdout R².
    """

    predicted_value: float
    confidence_interval_lower: float
    confidence_interval_upper: float
    model_confidence: float


class TrendPredictor:
    """A fit/predict wrapper around a Random Forest or XGBoost regressor.

    Attributes:
        parameter: The parameter this predictor forecasts (for
            logging/metadata only - the predictor itself is agnostic
            to what its features/target mean).
        horizon: The forecast horizon this predictor was trained for
            (for logging/metadata only).
        algorithm: ``"random_forest"`` or ``"xgboost"``.
        metrics_: Holdout evaluation metrics (``mae``/``rmse``/``r2``)
            from the most recent :meth:`train` call, or ``{}`` if
            untrained.
    """

    def __init__(
        self,
        parameter: str,
        horizon: str,
        algorithm: Algorithm = "random_forest",
        n_estimators: int = 100,
        random_state: int = 42,
    ) -> None:
        """Initialize an untrained predictor.

        Args:
            parameter: The parameter this predictor forecasts.
            horizon: The forecast horizon (e.g. ``"next_hour"``).
            algorithm: ``"random_forest"`` (default; always
                available) or ``"xgboost"`` (falls back to
                ``"random_forest"`` with a logged warning if the
                ``xgboost`` package is not importable).
            n_estimators: Number of trees. Kept modest by default so
                training stays fast on a laptop.
            random_state: Random seed for reproducibility.
        """
        self.parameter = parameter
        self.horizon = horizon
        self.n_estimators = n_estimators
        self.random_state = random_state
        self.algorithm = self._resolve_algorithm(algorithm)

        self._model = None
        self.feature_names_: List[str] = []
        self.metrics_: dict = {}

    def _resolve_algorithm(self, algorithm: Algorithm) -> Algorithm:
        """Fall back to Random Forest if XGBoost isn't importable.

        Args:
            algorithm: The requested algorithm.

        Returns:
            ``algorithm`` unchanged, or ``"random_forest"`` if
            ``"xgboost"`` was requested but the package is missing.
        """
        if algorithm == "xgboost":
            try:
                import xgboost  # noqa: F401
            except ImportError:
                logger.warning("xgboost is not installed; falling back to random_forest.")
                return "random_forest"
        return algorithm

    def _build_estimator(self):
        """Construct the underlying scikit-learn/XGBoost estimator.

        Returns:
            An unfitted regressor instance.
        """
        if self.algorithm == "xgboost":
            from xgboost import XGBRegressor

            return XGBRegressor(
                n_estimators=self.n_estimators,
                random_state=self.random_state,
                max_depth=6,
                learning_rate=0.1,
                n_jobs=-1,
            )
        return RandomForestRegressor(
            n_estimators=self.n_estimators,
            random_state=self.random_state,
            n_jobs=-1,
        )

    def train(self, X: pd.DataFrame, y: pd.Series) -> "TrendPredictor":
        """Train on chronologically ordered features/target and evaluate on a holdout.

        The most recent ``_HOLDOUT_FRACTION`` of rows are held out
        (not shuffled - respecting time order avoids leaking future
        information into the training set) for the MAE/RMSE/R²
        evaluation stored in :attr:`metrics_`; the model is then
        refit on the *full* dataset for the strongest possible final
        model.

        Args:
            X: Feature frame, chronologically ordered (oldest first).
            y: Target series, aligned with ``X``.

        Returns:
            ``self``, for chaining.

        Raises:
            ValueError: If ``X``/``y`` have fewer than 4 rows (too few
                to hold out any rows for evaluation).
        """
        if len(X) < 4:
            raise ValueError(f"Need at least 4 rows to train a TrendPredictor, got {len(X)}.")

        self.feature_names_ = list(X.columns)
        split_index = max(1, int(len(X) * (1 - _HOLDOUT_FRACTION)))
        X_train, X_test = X.iloc[:split_index], X.iloc[split_index:]
        y_train, y_test = y.iloc[:split_index], y.iloc[split_index:]

        evaluation_model = self._build_estimator()
        evaluation_model.fit(X_train, y_train)
        if len(X_test) > 0:
            predictions = evaluation_model.predict(X_test)
            self.metrics_ = regression_metrics(y_test.to_numpy(), predictions)
        else:
            self.metrics_ = {"mae": 0.0, "rmse": 0.0, "r2": 0.0}

        self._model = self._build_estimator()
        self._model.fit(X, y)

        logger.info(
            f"TrendPredictor trained: parameter={self.parameter} horizon={self.horizon} "
            f"algorithm={self.algorithm} rows={len(X)} metrics={self.metrics_}"
        )
        return self

    @property
    def is_trained(self) -> bool:
        """Whether :meth:`train` has been called successfully.

        Returns:
            ``True`` if the predictor is ready for :meth:`predict`.
        """
        return self._model is not None

    def predict(self, X: pd.DataFrame) -> TrendPrediction:
        """Predict the target for the most recent feature row in ``X``.

        Args:
            X: A feature frame containing at least one row, whose last
                row is used as the prediction input. Must contain
                every column in :attr:`feature_names_`.

        Returns:
            A :class:`TrendPrediction`.

        Raises:
            ModelNotTrainedError: If called before :meth:`train`.
            ValueError: If ``X`` is empty.
        """
        if not self.is_trained:
            raise ModelNotTrainedError("TrendPredictor.predict() called before train().")
        if X.empty:
            raise ValueError("Cannot predict from an empty feature frame.")

        latest_row = X[self.feature_names_].iloc[[-1]]
        point_estimate = float(self._model.predict(latest_row)[0])

        spread = self._per_tree_std(latest_row)
        margin = _CI_Z_SCORE * spread

        return TrendPrediction(
            predicted_value=round(point_estimate, 4),
            confidence_interval_lower=round(point_estimate - margin, 4),
            confidence_interval_upper=round(point_estimate + margin, 4),
            model_confidence=round(confidence_from_r2(self.metrics_.get("r2", 0.0)), 4),
        )

    def _per_tree_std(self, row: pd.DataFrame) -> float:
        """Estimate prediction uncertainty from per-tree prediction spread.

        Args:
            row: A single-row feature frame.

        Returns:
            The standard deviation across individual trees'
            predictions (Random Forest and XGBoost both expose an
            ``estimators_``-style ensemble); ``0.0`` if unavailable.
        """
        estimators = getattr(self._model, "estimators_", None)
        if estimators is None or len(estimators) == 0:
            return 0.0
        try:
            row_values = row.to_numpy()
            tree_predictions = np.array([float(np.ravel(tree.predict(row_values))[0]) for tree in estimators])
            return float(tree_predictions.std())
        except Exception:  # pragma: no cover - defensive; estimator API differences
            return 0.0


__all__ = ["TrendPredictor", "TrendPrediction", "ModelNotTrainedError", "Algorithm"]
