"""Calculator registry.

Implements a registry pattern so every calculation module can
self-register under a canonical key (e.g. ``"tds"``,
``"river_discharge"``) and future modules (dashboard, APIs, ML,
reports) can request a calculation purely by key, with zero
knowledge of which class implements it or which file it lives in::

    from app.analytics.calculator_registry import get_calculator

    calculator = get_calculator("tds")
    result = calculator.calculate(inputs)

Every calculator module (``water_quality.py``, ``oxygen.py``, ...)
registers its calculator classes using the :func:`register` decorator
at import time. :mod:`app.analytics.analytics_engine` is responsible
for importing every calculator module so registration actually runs.
"""

from __future__ import annotations

from typing import Dict, List, Type

from app.analytics.base import BaseCalculator
from app.utils.exceptions import ConfigurationError
from app.utils.logger import get_logger

logger = get_logger(__name__)

_REGISTRY: Dict[str, BaseCalculator] = {}


def register(key: str):
    """Class decorator that registers a calculator under ``key``.

    Args:
        key: The canonical, unique registry key for this calculator
            (e.g. ``"tds"``). Conventionally lowercase snake_case.

    Returns:
        A decorator that registers the decorated class's singleton
        instance and returns the class unchanged.

    Raises:
        ConfigurationError: If ``key`` is already registered by a
            different class (guards against accidental duplicate
            registration).
    """

    def _decorator(cls: Type[BaseCalculator]) -> Type[BaseCalculator]:
        if key in _REGISTRY and type(_REGISTRY[key]) is not cls:
            raise ConfigurationError(
                f"Duplicate analytics calculator registration for key '{key}': "
                f"already registered as {type(_REGISTRY[key]).__name__}, "
                f"cannot also register {cls.__name__}."
            )
        instance = cls()
        _REGISTRY[key] = instance
        logger.info(f"Registered analytics calculator: key={key!r} class={cls.__name__}")
        return cls

    return _decorator


def get_calculator(key: str) -> BaseCalculator:
    """Look up a registered calculator by key.

    Args:
        key: The calculator's registry key (e.g. ``"river_discharge"``).

    Returns:
        The registered :class:`~app.analytics.base.BaseCalculator`
        instance.

    Raises:
        KeyError: If no calculator is registered under ``key``.
    """
    try:
        return _REGISTRY[key]
    except KeyError as exc:
        raise KeyError(
            f"No analytics calculator registered under key '{key}'. "
            f"Available keys: {sorted(_REGISTRY)}"
        ) from exc


def is_registered(key: str) -> bool:
    """Check whether a calculator is registered under ``key``.

    Args:
        key: The calculator's registry key.

    Returns:
        ``True`` if a calculator is registered under ``key``.
    """
    return key in _REGISTRY


def registered_keys() -> List[str]:
    """List every currently registered calculator key.

    Returns:
        A sorted list of registry keys.
    """
    return sorted(_REGISTRY)


def all_calculators() -> Dict[str, BaseCalculator]:
    """Return a shallow copy of the full registry.

    Returns:
        A dict mapping registry key -> calculator instance.
    """
    return dict(_REGISTRY)


def _reset_registry_for_tests() -> None:
    """Clear the registry.

    Intended for use only by the test suite, to verify registration
    behavior in isolation without cross-test pollution. Not part of
    the public API.
    """
    _REGISTRY.clear()
