"""Unit tests for :mod:`app.ml.model_manager`."""

from __future__ import annotations

import time

import pytest

from app.ml.model_manager import ModelManager
from app.utils.exceptions import NotFoundError


def test_has_model_false_when_never_saved(tmp_path) -> None:
    manager = ModelManager(str(tmp_path))
    assert manager.has_model("nonexistent") is False


def test_save_and_load_round_trips_the_object(tmp_path) -> None:
    manager = ModelManager(str(tmp_path))
    obj = {"weights": [1, 2, 3]}
    manager.save("demo_model", obj, algorithm="dummy", metrics={"mae": 0.1}, training_rows=42)

    loaded_obj, metadata = manager.load("demo_model")
    assert loaded_obj == obj
    assert metadata.algorithm == "dummy"
    assert metadata.metrics == {"mae": 0.1}
    assert metadata.training_rows == 42
    assert metadata.model_name == "demo_model"


def test_load_unknown_model_raises_not_found(tmp_path) -> None:
    manager = ModelManager(str(tmp_path))
    with pytest.raises(NotFoundError):
        manager.load("nonexistent")


def test_load_unknown_version_raises_not_found(tmp_path) -> None:
    manager = ModelManager(str(tmp_path))
    manager.save("demo_model", {"a": 1}, algorithm="dummy")
    with pytest.raises(NotFoundError):
        manager.load("demo_model", version="not-a-real-version")


def test_save_twice_load_returns_latest(tmp_path) -> None:
    manager = ModelManager(str(tmp_path))
    manager.save("demo_model", {"version": 1}, algorithm="dummy")
    time.sleep(0.01)
    manager.save("demo_model", {"version": 2}, algorithm="dummy")

    loaded_obj, _ = manager.load("demo_model")
    assert loaded_obj == {"version": 2}


def test_list_versions_returns_every_saved_version(tmp_path) -> None:
    manager = ModelManager(str(tmp_path))
    assert manager.list_versions("demo_model") == []
    manager.save("demo_model", {"v": 1}, algorithm="dummy")
    time.sleep(0.01)
    manager.save("demo_model", {"v": 2}, algorithm="dummy")
    versions = manager.list_versions("demo_model")
    assert len(versions) == 2
    assert versions == sorted(versions)


def test_load_specific_version(tmp_path) -> None:
    manager = ModelManager(str(tmp_path))
    metadata_v1 = manager.save("demo_model", {"v": 1}, algorithm="dummy")
    time.sleep(0.01)
    manager.save("demo_model", {"v": 2}, algorithm="dummy")

    loaded_obj, metadata = manager.load("demo_model", version=metadata_v1.version)
    assert loaded_obj == {"v": 1}
    assert metadata.version == metadata_v1.version


def test_models_dir_created_if_missing(tmp_path) -> None:
    target = tmp_path / "nested" / "models"
    assert not target.exists()
    ModelManager(str(target))
    assert target.exists()
