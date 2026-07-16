"""Historical Analytics & Trend Engine.

This package analyzes *already stored* sensor readings and derived
analytics (never live/serial data directly) to produce statistical
summaries, trend classifications, seasonal groupings, and simple
parameter comparisons over a configurable historical time window.

Scope
-----
This module is intentionally statistics-only:

    * No Machine Learning, forecasting, or prediction.
    * No alerting or report generation.
    * No new database tables - it reads through the existing
      :class:`app.database.service.DatabaseService` facade only.

It exists to give a future ML/forecasting module (and the dashboard's
Trends page) a single, reusable, well-tested source of historical
statistics rather than every consumer recomputing its own.

Submodules
----------
    * :mod:`app.historical.statistics` - pure numeric summary
      functions (min/max/mean/median/std-dev/...).
    * :mod:`app.historical.trends` - trend direction/rate-of-change
      classification via simple linear regression.
    * :mod:`app.historical.aggregation` - hourly/daily/weekly/monthly
      bucketed aggregation.
    * :mod:`app.historical.seasonal` - grouping by hour/day/week/
      month/season/year.
    * :mod:`app.historical.comparison` - correlation/comparison of two
      parameter series.
    * :mod:`app.historical.utils` - shared time-window resolution and
      the data-fetching helper every service method builds on.
    * :mod:`app.historical.schemas` - Pydantic response models used
      directly as this package's public data contracts (and as the
      REST API's ``response_model``\\ s).
    * :mod:`app.historical.service` - :class:`HistoricalAnalyticsService`,
      the single façade the API layer (and any future module) should
      depend on.
"""

from __future__ import annotations

from app.historical.service import HistoricalAnalyticsService

__all__ = ["HistoricalAnalyticsService"]
