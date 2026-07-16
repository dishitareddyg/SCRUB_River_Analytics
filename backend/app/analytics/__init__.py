"""Analytics Engine package.

The mathematical core of the River Intelligence Platform: computes
derived river parameters (TDS, salinity, oxygen saturation/deficit,
water density, channel geometry, flow velocity, discharge, sediment
load) from validated sensor data retrieved from the database layer
(``app.database``). Never communicates with the Arduino/serial layer
directly.

Structure:
    - ``result.py``: :class:`~app.analytics.result.CalculationResult`
      and :class:`~app.analytics.result.CalculationStatus` - the
      structured output contract every calculator returns.
    - ``base.py``: :class:`~app.analytics.base.BaseCalculator`, the
      common interface every calculator implements, plus
      :class:`~app.analytics.base.CalculatorMetadata` (formula name,
      reference, units, assumptions, limitations, valid ranges).
    - ``calculator_registry.py``: the ``@register(key)`` decorator and
      :func:`~app.analytics.calculator_registry.get_calculator`
      lookup - future modules request a calculation by key without
      knowing which class or file implements it.
    - ``config.py``: loads every equation-selection flag, coefficient,
      and correction factor from ``app/config/analytics.yaml`` - no
      calculator hardcodes a numeric constant.
    - ``equations.py``: the underlying published formulas, shared
      across calculators (no duplicated equations).
    - ``water_quality.py``, ``oxygen.py``, ``density.py``,
      ``geometry.py``, ``hydrology.py``, ``sediment.py``: the
      calculator implementations, one derived parameter each (see
      each module's docstring for its registry key(s)).
    - ``analytics_engine.py``: :class:`~app.analytics.analytics_engine.AnalyticsEngine`,
      the database-integration facade future modules should use.

Explicitly out of scope for this module (see the project README):
Water Quality Index, River Health Score, Flood/Pollution/Thermal-
Stress/Habitat/Algal-Bloom risk scoring, machine learning, prediction,
the dashboard, REST APIs, and reports. This module also never persists
its results - storage is handled by a later module.
"""

from app.analytics.analytics_engine import AnalyticsEngine
from app.analytics.calculator_registry import get_calculator, registered_keys
from app.analytics.result import CalculationResult, CalculationStatus

__all__ = [
    "AnalyticsEngine",
    "get_calculator",
    "registered_keys",
    "CalculationResult",
    "CalculationStatus",
]
