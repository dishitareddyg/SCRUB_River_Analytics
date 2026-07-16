"""Analytics Engine.

The single integration point between the Analytics Engine and the
rest of the platform. :class:`AnalyticsEngine`:

    1. Retrieves the latest validated sensor readings needed by a
       calculator from :class:`app.database.service.DatabaseService`
       (never talks to the Arduino/serial layer directly).
    2. Resolves a calculator by key via the calculator registry.
    3. Computes the derived parameter and returns a structured
       :class:`~app.analytics.result.CalculationResult`.

It deliberately does **not** persist results - storage is out of
scope for this module and will be handled by a later one (see the
module's ``README`` section).

Usage::

    from app.analytics.analytics_engine import AnalyticsEngine

    engine = AnalyticsEngine()
    result = engine.compute("tds")
    all_results = engine.compute_all(device_name="river-bot-01")
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional

# Side-effect imports: importing each calculator module runs its
# `@register(...)` decorators, populating the calculator registry.
# The engine is the one place responsible for knowing every
# calculator module exists - nothing else in the codebase needs to
# import them directly.
import app.analytics.density  # noqa: F401
import app.analytics.geometry  # noqa: F401
import app.analytics.hydrology  # noqa: F401
import app.analytics.oxygen  # noqa: F401
import app.analytics.sediment  # noqa: F401
import app.analytics.water_quality  # noqa: F401
from app.analytics.calculator_registry import all_calculators, get_calculator, registered_keys
from app.analytics.config import AnalyticsConfig, get_analytics_config
from app.analytics.result import CalculationResult
from app.database.service import DatabaseService, get_database_service
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Maps a calculator's abstract input name (e.g. "conductivity") to the
# canonical `sensor_key` it should be read from in the database (see
# `app/config/sensors.yaml`). Kept as one explicit, overridable table
# rather than scattered across calculator modules, so re-pointing an
# input at a different sensor channel is a one-line change here - no
# calculator code changes required.
DEFAULT_SENSOR_KEY_MAP: Dict[str, str] = {
    "dissolved_oxygen": "dissolved_oxygen",
    "ph_level": "ph_level",
    "conductivity": "conductivity",
    "orp": "orp",
    "turbidity": "turbidity",
    "water_temperature": "water_temperature",
    "air_temperature": "air_temperature",
    "humidity": "humidity",
    "barometric_pressure": "barometric_pressure",
    "water_level": "water_level",
    "river_depth": "river_depth",
    "rainfall": "rainfall",
    "wind_speed": "wind_speed",
    "par": "par",
}


class AnalyticsEngine:
    """Computes derived river parameters from validated sensor data.

    Attributes:
        None (all collaborators are private; interact only through
        the public methods below).
    """

    def __init__(
        self,
        database_service: Optional[DatabaseService] = None,
        config: Optional[AnalyticsConfig] = None,
        sensor_key_map: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initialize the engine.

        Args:
            database_service: The database facade to read validated
                readings from. Defaults to the process-wide
                :func:`app.database.service.get_database_service`
                singleton. Overridable for testing.
            config: The Analytics Engine configuration. Defaults to
                the process-wide cached
                :func:`app.analytics.config.get_analytics_config`.
                Overridable for testing/what-if scenarios.
            sensor_key_map: Overrides for
                :data:`DEFAULT_SENSOR_KEY_MAP`, merged on top of the
                defaults. Lets a deployment repoint a calculator's
                abstract input at a differently-named sensor channel
                without any code changes elsewhere.
        """
        self._db = database_service or get_database_service()
        self._config = config or get_analytics_config()
        self._sensor_key_map = dict(DEFAULT_SENSOR_KEY_MAP)
        if sensor_key_map:
            self._sensor_key_map.update(sensor_key_map)

    # ------------------------------------------------------------------
    # Input resolution
    # ------------------------------------------------------------------

    def _fetch_latest_inputs(
        self, input_names: Iterable[str], device_name: Optional[str] = None
    ) -> Dict[str, Optional[float]]:
        """Fetch the latest validated value for each named input.

        Args:
            input_names: The abstract input names to resolve (e.g.
                ``{"conductivity", "water_temperature"}``).
            device_name: Optional device filter. When ``None``, the
                latest reading across all devices is used for each
                sensor.

        Returns:
            A mapping of input name -> latest numeric value, or
            ``None`` for any input with no available/valid reading.
        """
        resolved: Dict[str, Optional[float]] = {}
        for input_name in input_names:
            sensor_key = self._sensor_key_map.get(input_name, input_name)
            readings = self._db.get_latest_readings(
                device_name=device_name, sensor_key=sensor_key, limit=1
            )
            value = readings[0].value if readings else None
            resolved[input_name] = value
        return resolved

    # ------------------------------------------------------------------
    # Computation
    # ------------------------------------------------------------------

    def compute(self, parameter_key: str, device_name: Optional[str] = None) -> CalculationResult:
        """Compute a single derived parameter from the latest sensor data.

        Args:
            parameter_key: The calculator's registry key (e.g.
                ``"tds"``, ``"river_discharge"``). See
                :func:`app.analytics.calculator_registry.registered_keys`
                for the full list.
            device_name: Optional device filter restricting which
                device's readings are used.

        Returns:
            The computed :class:`~app.analytics.result.CalculationResult`.

        Raises:
            KeyError: If ``parameter_key`` is not a registered
                calculator.
        """
        calculator = get_calculator(parameter_key)
        needed_inputs = set(calculator.required_inputs()) | set(calculator.optional_inputs())
        inputs = self._fetch_latest_inputs(needed_inputs, device_name=device_name)
        return calculator.calculate(inputs, self._config)

    def compute_all(self, device_name: Optional[str] = None) -> Dict[str, CalculationResult]:
        """Compute every registered derived parameter from the latest sensor data.

        Fetches each distinct required sensor value only once (even
        if multiple calculators share an input, e.g.
        ``water_temperature``), then runs every registered calculator
        against that shared input set.

        Args:
            device_name: Optional device filter restricting which
                device's readings are used.

        Returns:
            A mapping of parameter key -> its
            :class:`~app.analytics.result.CalculationResult`.
        """
        calculators = all_calculators()

        all_needed_inputs: set[str] = set()
        for calculator in calculators.values():
            all_needed_inputs |= set(calculator.required_inputs())
            all_needed_inputs |= set(calculator.optional_inputs())

        inputs = self._fetch_latest_inputs(all_needed_inputs, device_name=device_name)

        results: Dict[str, CalculationResult] = {}
        for key, calculator in calculators.items():
            results[key] = calculator.calculate(inputs, self._config)
        return results

    def available_parameters(self) -> list[str]:
        """List every derived parameter this engine can currently compute.

        Returns:
            A sorted list of registered calculator keys.
        """
        return registered_keys()
