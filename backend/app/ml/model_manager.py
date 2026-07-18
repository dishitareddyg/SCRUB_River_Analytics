"""Model loading, saving, and versioning via joblib.

Every trained object in ``app.ml`` (an
:class:`~app.ml.anomaly_detector.AnomalyDetector`, a
:class:`~app.ml.trend_predictor.TrendPredictor`, or any other
picklable estimator wrapper) is persisted through this single class,
so every model shares one on-disk layout, one versioning scheme, and
one retraining interface - callers never touch ``joblib`` directly.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import joblib

from app.utils.exceptions import NotFoundError
from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ModelMetadata:
    """Metadata recorded alongside every saved model version.

    Attributes:
        model_name: The logical model name (e.g.
            ``"trend_dissolved_oxygen_next_hour"``).
        version: The version identifier (a UTC timestamp string).
        trained_at: When training completed (UTC, ISO 8601).
        algorithm: A short label for the underlying algorithm (e.g.
            ``"random_forest"``, ``"isolation_forest"``).
        metrics: Evaluation metrics captured at training time (e.g.
            ``{"mae": 0.12, "rmse": 0.18, "r2": 0.81}``).
        training_rows: Number of rows the model was trained on.
        extra: Any additional free-form metadata a caller wants
            recorded (e.g. the feature column list).
    """

    model_name: str
    version: str
    trained_at: str
    algorithm: str
    metrics: Dict[str, float] = field(default_factory=dict)
    training_rows: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)


class ModelManager:
    """Saves/loads/versions trained models on disk via joblib.

    On-disk layout under ``models_dir``::

        <model_name>/
            <version>.joblib          # the pickled model object
            <version>.json            # its ModelMetadata
            latest.json                # {"version": "<version>"} pointer

    Attributes:
        models_dir: Root directory every model is stored under.
    """

    def __init__(self, models_dir: str) -> None:
        """Initialize the manager, creating ``models_dir`` if needed.

        Args:
            models_dir: Root directory every model is stored under.
                Created (including parents) if it doesn't exist yet.
        """
        self.models_dir = Path(models_dir)
        self.models_dir.mkdir(parents=True, exist_ok=True)

    def _model_dir(self, model_name: str) -> Path:
        """Return (and create) the directory for one logical model.

        Args:
            model_name: The logical model name.

        Returns:
            The model's directory path.
        """
        path = self.models_dir / model_name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def save(
        self,
        model_name: str,
        model: Any,
        algorithm: str,
        metrics: Optional[Dict[str, float]] = None,
        training_rows: int = 0,
        extra: Optional[Dict[str, Any]] = None,
    ) -> ModelMetadata:
        """Persist a new version of ``model`` and mark it as the latest.

        Args:
            model_name: The logical model name.
            model: The picklable, already-trained model object.
            algorithm: A short label for the underlying algorithm.
            metrics: Evaluation metrics to record.
            training_rows: Number of rows the model was trained on.
            extra: Any additional free-form metadata to record.

        Returns:
            The saved version's :class:`ModelMetadata`.
        """
        model_dir = self._model_dir(model_name)
        version = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")

        joblib.dump(model, model_dir / f"{version}.joblib")

        metadata = ModelMetadata(
            model_name=model_name,
            version=version,
            trained_at=datetime.now(timezone.utc).isoformat(),
            algorithm=algorithm,
            metrics=metrics or {},
            training_rows=training_rows,
            extra=extra or {},
        )
        (model_dir / f"{version}.json").write_text(json.dumps(asdict(metadata), indent=2))
        (model_dir / "latest.json").write_text(json.dumps({"version": version}))

        logger.info(f"Model saved: name={model_name} version={version} algorithm={algorithm} metrics={metrics}")
        return metadata

    def load(self, model_name: str, version: Optional[str] = None) -> tuple[Any, ModelMetadata]:
        """Load a model (its latest version, by default) and its metadata.

        Args:
            model_name: The logical model name.
            version: A specific version identifier. Defaults to the
                most recently saved version.

        Returns:
            A ``(model, metadata)`` tuple.

        Raises:
            NotFoundError: If ``model_name`` has never been saved, or
                ``version`` doesn't exist for it.
        """
        model_dir = self.models_dir / model_name
        resolved_version = version or self._latest_version(model_name)

        model_path = model_dir / f"{resolved_version}.joblib"
        metadata_path = model_dir / f"{resolved_version}.json"
        if not model_path.exists() or not metadata_path.exists():
            raise NotFoundError(f"No saved model '{model_name}' version '{resolved_version}' found.")

        model = joblib.load(model_path)
        metadata = ModelMetadata(**json.loads(metadata_path.read_text()))
        return model, metadata

    def _latest_version(self, model_name: str) -> str:
        """Resolve the latest saved version identifier for a model.

        Args:
            model_name: The logical model name.

        Returns:
            The latest version string.

        Raises:
            NotFoundError: If ``model_name`` has never been saved.
        """
        latest_path = self.models_dir / model_name / "latest.json"
        if not latest_path.exists():
            raise NotFoundError(f"No saved model named '{model_name}' found.")
        return json.loads(latest_path.read_text())["version"]

    def has_model(self, model_name: str) -> bool:
        """Check whether any version of ``model_name`` has been saved.

        Args:
            model_name: The logical model name.

        Returns:
            ``True`` if at least one version exists.
        """
        return (self.models_dir / model_name / "latest.json").exists()

    def list_versions(self, model_name: str) -> List[str]:
        """List every saved version of ``model_name``, oldest first.

        Args:
            model_name: The logical model name.

        Returns:
            A sorted list of version identifiers (empty if
            ``model_name`` has never been saved).
        """
        model_dir = self.models_dir / model_name
        if not model_dir.exists():
            return []
        return sorted(p.stem for p in model_dir.glob("*.joblib"))


__all__ = ["ModelManager", "ModelMetadata"]
