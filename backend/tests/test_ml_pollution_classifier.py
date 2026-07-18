"""Unit tests for :mod:`app.ml.pollution_classifier`."""

from __future__ import annotations

import pytest

from app.ml.pollution_classifier import FeatureSnapshot, PollutionClassifier
from app.ml.utils import PollutionSource


def test_probabilities_sum_to_one() -> None:
    classifier = PollutionClassifier()
    result = classifier.classify(FeatureSnapshot())
    assert sum(result.probabilities.values()) == pytest.approx(1.0, abs=1e-3)


def test_every_source_is_present_in_distribution() -> None:
    classifier = PollutionClassifier()
    result = classifier.classify(FeatureSnapshot())
    expected_keys = {source.value for source in PollutionSource}
    assert set(result.probabilities.keys()) == expected_keys


def test_empty_snapshot_defaults_toward_unknown_or_natural() -> None:
    classifier = PollutionClassifier()
    result = classifier.classify(FeatureSnapshot())
    assert result.most_likely_source in (
        PollutionSource.UNKNOWN.value,
        PollutionSource.NATURAL_VARIATION.value,
    )


def test_domestic_sewage_signature_scores_highest() -> None:
    classifier = PollutionClassifier()
    snapshot = FeatureSnapshot(
        dissolved_oxygen_trend_percent=-25.0,
        conductivity_trend_percent=20.0,
        orp=50.0,
        turbidity_trend_percent=20.0,
    )
    result = classifier.classify(snapshot)
    assert result.most_likely_source == PollutionSource.DOMESTIC_SEWAGE.value
    assert any("domestic_sewage" in note for note in result.notes)


def test_stormwater_signature_scores_highest() -> None:
    classifier = PollutionClassifier()
    snapshot = FeatureSnapshot(rainfall_trend_percent=80.0, turbidity_trend_percent=60.0)
    result = classifier.classify(snapshot)
    assert result.most_likely_source == PollutionSource.STORMWATER.value


def test_industrial_effluent_signature_scores_highest() -> None:
    classifier = PollutionClassifier()
    snapshot = FeatureSnapshot(conductivity_trend_percent=50.0, ph_level=4.5, orp=450.0, turbidity_trend_percent=1.0)
    result = classifier.classify(snapshot)
    assert result.most_likely_source == PollutionSource.INDUSTRIAL_EFFLUENT.value


def test_stable_trends_favor_natural_variation() -> None:
    classifier = PollutionClassifier()
    snapshot = FeatureSnapshot(
        dissolved_oxygen_trend_percent=1.0,
        conductivity_trend_percent=-2.0,
        turbidity_trend_percent=0.5,
    )
    result = classifier.classify(snapshot)
    assert result.most_likely_source == PollutionSource.NATURAL_VARIATION.value


def test_probabilities_always_sum_to_one_under_extreme_input() -> None:
    classifier = PollutionClassifier()
    # An extreme snapshot designed to max out every rule simultaneously.
    snapshot = FeatureSnapshot(
        dissolved_oxygen_trend_percent=-90.0,
        conductivity_trend_percent=90.0,
        orp=-50.0,
        turbidity_trend_percent=90.0,
        rainfall_trend_percent=200.0,
        ph_level=2.0,
    )
    result = classifier.classify(snapshot)
    assert sum(result.probabilities.values()) == pytest.approx(1.0, abs=1e-3)
    assert min(result.probabilities.values()) > 0.0
