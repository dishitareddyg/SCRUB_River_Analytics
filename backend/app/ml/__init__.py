"""AI Decision Support Engine.

This package is the platform's lightweight, classical-ML layer. It
consumes the same data every other module already reads through —
:class:`app.database.service.DatabaseService` (raw sensor readings)
and :class:`app.historical.service.HistoricalAnalyticsService`
(statistics/trends over a time window) — and adds:

    * **Trend Prediction** — short-horizon forecasts (next hour/day/
      week) for key parameters (DO, pH, conductivity, water
      temperature, water level, river discharge) via
      :class:`~app.ml.trend_predictor.TrendPredictor`
      (Random Forest / XGBoost regression).
    * **Anomaly Detection** — a lightweight Isolation Forest over the
      current multi-sensor snapshot, via
      :class:`~app.ml.anomaly_detector.AnomalyDetector`.
    * **Pollution Source Probability** — a rule-assisted probability
      distribution over candidate pollution sources, via
      :class:`~app.ml.pollution_classifier.PollutionClassifier`.
    * **River Health Forecast** — a composite health score and its
      short-horizon forecast, via
      :class:`~app.ml.river_health_predictor.RiverHealthPredictor`.

Explicitly **no deep learning** (no TensorFlow/PyTorch, no neural
networks, no LLMs), **no online learning**, and **no cloud/distributed/
GPU** training — every estimator here is a small, CPU-only
scikit-learn/XGBoost model chosen to train and predict comfortably on
a standard laptop, on demand, from data already sitting in the
existing database.

Submodules
----------
    * :mod:`app.ml.feature_engineering` - reusable, configurable
      feature functions (rolling stats, rate of change, calendar
      features, lag features, parameter "change" features) over a
      pandas :class:`~pandas.DataFrame`.
    * :mod:`app.ml.dataset_builder` - turns historical database
      records (via :mod:`app.historical`) into an ML-ready, resampled,
      cleaned, optionally normalized :class:`~pandas.DataFrame`.
    * :mod:`app.ml.anomaly_detector` - the Isolation Forest wrapper.
    * :mod:`app.ml.trend_predictor` - the Random Forest / XGBoost
      regressor wrapper, with a confidence interval derived from the
      forest's per-tree prediction spread.
    * :mod:`app.ml.pollution_classifier` - the rule-assisted pollution
      source classifier.
    * :mod:`app.ml.river_health_predictor` - the composite river
      health score + forecast.
    * :mod:`app.ml.model_manager` - joblib-based model
      loading/saving/versioning.
    * :mod:`app.ml.trainer` - the offline training pipeline that ties
      the above together and persists trained models.
    * :mod:`app.ml.inference` - :class:`~app.ml.inference.MLInferenceService`,
      the on-demand façade the REST API depends on (lazily trains and
      caches a model the first time it's needed, rather than requiring
      a separate training step before the API can respond).
    * :mod:`app.ml.schemas` - Pydantic response models.
    * :mod:`app.ml.utils` - shared constants/enums (horizons,
      pollution source labels, health categories) and small metric
      helpers.
"""

from __future__ import annotations

from app.ml.inference import MLInferenceService

__all__ = ["MLInferenceService"]
