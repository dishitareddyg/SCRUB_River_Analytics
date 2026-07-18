"""Shared helpers for the AI Decision Support Engine (``app/ml``) test suite.

Not a pytest ``conftest.py`` on purpose, mirroring the pattern used by
``tests/database_test_helpers.py``, ``tests/analytics_test_helpers.py``,
and ``tests/historical_test_helpers.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterator, Optional

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_settings_dependency
from app.config.settings import Settings, get_settings
from app.database.service import DatabaseService, get_database_service
from app.main import app
from tests.historical_test_helpers import build_isolated_db_service

#: Default sensors seeded by :func:`seed_ml_sensor_data` - matches
#: app.ml.utils.DEFAULT_MONITORING_PARAMETERS.
ML_SENSOR_KEYS = [
    "dissolved_oxygen",
    "ph_level",
    "conductivity",
    "turbidity",
    "orp",
    "water_temperature",
    "water_level",
    "rainfall",
]


def build_ml_settings(model_dir: str, min_training_samples: int = 20) -> Settings:
    """Build a :class:`Settings` instance pointed at an isolated model directory.

    Args:
        model_dir: Directory (typically a pytest ``tmp_path``) trained
            models should be written to/read from for this test.
        min_training_samples: Lowered minimum training sample count so
            small seeded datasets are still trainable in tests.

    Returns:
        A :class:`Settings` instance safe to use in tests (never
        pointed at the real ``app/ml/artifacts`` directory).
    """
    return Settings(ml_model_dir=model_dir, ml_min_training_samples=min_training_samples)


def seed_ml_sensor_data(
    db: DatabaseService,
    device_name: str = "river-bot-01",
    days: int = 15,
    seed: int = 42,
    sensor_keys: Optional[list] = None,
) -> datetime:
    """Seed hourly, mildly randomized readings for every ML monitoring sensor.

    Args:
        db: The target :class:`DatabaseService`.
        device_name: Device name to register and attribute readings to.
        days: Number of days of hourly history to generate.
        seed: Random seed, for reproducible test data.
        sensor_keys: Sensor keys to seed. Defaults to
            :data:`ML_SENSOR_KEYS`.

    Returns:
        The timestamp used for the first (oldest) reading.
    """
    db.register_device(device_name)
    sensor_keys = sensor_keys or ML_SENSOR_KEYS
    for key in sensor_keys:
        db.register_sensor(sensor_key=key, display_name=key, unit="unit")

    rng = np.random.default_rng(seed)
    base = datetime.now(timezone.utc) - timedelta(days=days)
    baselines: Dict[str, float] = {
        "dissolved_oxygen": 7.5,
        "ph_level": 7.2,
        "conductivity": 300.0,
        "turbidity": 5.0,
        "orp": 200.0,
        "water_temperature": 18.0,
        "water_level": 2.0,
        "rainfall": 0.5,
    }
    for i in range(days * 24):
        ts = base + timedelta(hours=i)
        for key in sensor_keys:
            baseline = baselines.get(key, 10.0)
            value = max(0.0, baseline + rng.normal(0, baseline * 0.05 + 0.05))
            db.save_sensor_reading(device_name=device_name, sensor_key=key, timestamp=ts, value=value)
    return base


@pytest.fixture
def ml_api_client(tmp_path: Path) -> Iterator[TestClient]:
    """Provide a :class:`TestClient` with an isolated database and model directory.

    Overrides both :func:`app.database.service.get_database_service`
    and :func:`app.api.dependencies.get_settings_dependency` for the
    duration of the test, so ML tests never touch the real database or
    write trained models into the repository's ``app/ml/artifacts``.

    Args:
        tmp_path: pytest's per-test temporary directory fixture.

    Yields:
        A :class:`TestClient` plus, via ``client.db_service``, direct
        access to the underlying isolated :class:`DatabaseService` for
        seeding data.
    """
    db_service = build_isolated_db_service()
    settings = build_ml_settings(str(tmp_path / "ml-models"))

    app.dependency_overrides[get_database_service] = lambda: db_service
    app.dependency_overrides[get_settings_dependency] = lambda: settings
    app.dependency_overrides[get_settings] = lambda: settings

    with TestClient(app) as client:
        client.db_service = db_service  # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.pop(get_database_service, None)
    app.dependency_overrides.pop(get_settings_dependency, None)
    app.dependency_overrides.pop(get_settings, None)
