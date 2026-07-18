"""Rule-assisted pollution source probability classifier.

No labeled pollution-event training data exists in this platform (it
would require ground-truth incident records this project does not
have), so this classifier is intentionally **rule-assisted** rather
than a trained classifier: each candidate source has a small set of
heuristic scoring rules over current sensor readings, their recent
trend, and derived analytics. Rule scores are normalized into a
probability distribution over all candidate sources - never a single
confident label - per this module's "do not claim certainty"
requirement. The interface (`classify()`) is deliberately trained-
model-shaped (``PollutionClassifier`` could later wrap a real
supervised classifier - e.g. once labeled incident data exists - by
implementing :meth:`score` differently) without over-engineering a
training path that has nothing to train on today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from app.ml.utils import PollutionSource, clamp
from app.utils.logger import get_logger

logger = get_logger(__name__)

#: A pollution-source classification is never reported with more than
#: this much confidence, however strongly a single rule fires -
#: reflects that this is a heuristic screening signal, not a
#: laboratory determination.
MAX_SOURCE_PROBABILITY = 0.85

#: Every candidate source is floored at this probability so the
#: distribution never implies a source has been fully ruled out from
#: a handful of readings.
MIN_SOURCE_PROBABILITY = 0.02


@dataclass
class FeatureSnapshot:
    """The current readings + short-term trend a rule can inspect.

    All fields are optional because not every deployment has every
    sensor; rules must treat a missing value as "no evidence either
    way", not as zero.

    Attributes:
        dissolved_oxygen: Current DO reading (mg/L).
        dissolved_oxygen_trend_percent: DO's percent change over the
            recent trend window (see
            ``app.historical.trends.TrendData.trend_percentage``).
        conductivity: Current conductivity reading (µS/cm).
        conductivity_trend_percent: Conductivity's recent percent
            change.
        turbidity: Current turbidity reading (NTU).
        turbidity_trend_percent: Turbidity's recent percent change.
        ph_level: Current pH reading.
        orp: Current ORP (oxidation-reduction potential) reading (mV).
        water_temperature: Current water temperature (°C).
        rainfall: Recent rainfall accumulation, if available.
        rainfall_trend_percent: Rainfall's recent percent change (a
            sharp rise signals an active storm event).
    """

    dissolved_oxygen: Optional[float] = None
    dissolved_oxygen_trend_percent: Optional[float] = None
    conductivity: Optional[float] = None
    conductivity_trend_percent: Optional[float] = None
    turbidity: Optional[float] = None
    turbidity_trend_percent: Optional[float] = None
    ph_level: Optional[float] = None
    orp: Optional[float] = None
    water_temperature: Optional[float] = None
    rainfall: Optional[float] = None
    rainfall_trend_percent: Optional[float] = None


@dataclass(frozen=True)
class PollutionClassification:
    """The result of :meth:`PollutionClassifier.classify`.

    Attributes:
        probabilities: Source key -> probability, summing to ``1.0``.
        most_likely_source: The highest-probability source.
        notes: Short, human-readable reasons the top rules fired
            (empty if no rule fired meaningfully, i.e. the result is
            effectively "unknown").
    """

    probabilities: Dict[str, float]
    most_likely_source: str
    notes: List[str] = field(default_factory=list)


def _score_domestic_sewage(f: FeatureSnapshot) -> tuple[float, Optional[str]]:
    """Score the Domestic Sewage hypothesis: low DO, elevated conductivity/turbidity, low ORP."""
    score = 0.0
    reasons = []
    if f.dissolved_oxygen_trend_percent is not None and f.dissolved_oxygen_trend_percent < -10:
        score += 0.35
        reasons.append("DO dropping sharply")
    if f.conductivity_trend_percent is not None and f.conductivity_trend_percent > 10:
        score += 0.25
        reasons.append("conductivity rising")
    if f.orp is not None and f.orp < 100:
        score += 0.25
        reasons.append("low ORP (reducing conditions)")
    if f.turbidity_trend_percent is not None and f.turbidity_trend_percent > 15:
        score += 0.15
        reasons.append("turbidity rising")
    return score, ("; ".join(reasons) if reasons else None)


def _score_agricultural_runoff(f: FeatureSnapshot) -> tuple[float, Optional[str]]:
    """Score the Agricultural Runoff hypothesis: rainfall-linked turbidity + conductivity rise, moderate DO drop."""
    score = 0.0
    reasons = []
    if f.rainfall_trend_percent is not None and f.rainfall_trend_percent > 20:
        score += 0.3
        reasons.append("recent rainfall")
    if f.turbidity_trend_percent is not None and f.turbidity_trend_percent > 25:
        score += 0.3
        reasons.append("turbidity spike")
    if f.conductivity_trend_percent is not None and 5 < f.conductivity_trend_percent <= 25:
        score += 0.2
        reasons.append("moderate conductivity rise")
    if f.dissolved_oxygen_trend_percent is not None and -15 < f.dissolved_oxygen_trend_percent < -3:
        score += 0.2
        reasons.append("moderate DO drop")
    return score, ("; ".join(reasons) if reasons else None)


def _score_industrial_effluent(f: FeatureSnapshot) -> tuple[float, Optional[str]]:
    """Score the Industrial Effluent hypothesis: sharp conductivity/pH/ORP deviation, little turbidity change."""
    score = 0.0
    reasons = []
    if f.conductivity_trend_percent is not None and abs(f.conductivity_trend_percent) > 30:
        score += 0.35
        reasons.append("sharp conductivity swing")
    if f.ph_level is not None and (f.ph_level < 6.0 or f.ph_level > 9.0):
        score += 0.3
        reasons.append("pH outside normal range")
    if f.orp is not None and (f.orp > 400 or f.orp < 0):
        score += 0.2
        reasons.append("abnormal ORP")
    if f.turbidity_trend_percent is not None and abs(f.turbidity_trend_percent) < 5:
        score += 0.15
        reasons.append("turbidity largely unchanged")
    return score, ("; ".join(reasons) if reasons else None)


def _score_stormwater(f: FeatureSnapshot) -> tuple[float, Optional[str]]:
    """Score the Stormwater hypothesis: rainfall-driven turbidity/flow spike, brief temperature drop."""
    score = 0.0
    reasons = []
    if f.rainfall_trend_percent is not None and f.rainfall_trend_percent > 50:
        score += 0.4
        reasons.append("heavy recent rainfall")
    if f.turbidity_trend_percent is not None and f.turbidity_trend_percent > 40:
        score += 0.35
        reasons.append("sharp turbidity spike")
    if f.water_temperature is not None and f.dissolved_oxygen_trend_percent is not None:
        score += 0.05  # weak corroborating signal only; not scored standalone
    return score, ("; ".join(reasons) if reasons else None)


def _score_natural_variation(f: FeatureSnapshot) -> tuple[float, Optional[str]]:
    """Score the Natural Variation hypothesis: everything within a modest range of change."""
    trend_values = [
        v
        for v in (f.dissolved_oxygen_trend_percent, f.conductivity_trend_percent, f.turbidity_trend_percent)
        if v is not None
    ]
    if not trend_values:
        return 0.1, None
    if all(abs(v) < 8 for v in trend_values):
        return 0.5, "all monitored trends within normal variation"
    return 0.05, None


#: Ordered (source, scoring function) pairs. Order only affects
#: tie-breaking in :func:`_pick_most_likely`, not the normalized
#: probabilities themselves.
_RULES: List[tuple] = [
    (PollutionSource.DOMESTIC_SEWAGE, _score_domestic_sewage),
    (PollutionSource.AGRICULTURAL_RUNOFF, _score_agricultural_runoff),
    (PollutionSource.INDUSTRIAL_EFFLUENT, _score_industrial_effluent),
    (PollutionSource.STORMWATER, _score_stormwater),
    (PollutionSource.NATURAL_VARIATION, _score_natural_variation),
]


class PollutionClassifier:
    """Classifies the probable source of an observed water-quality shift.

    Stateless and dependency-free by design (pure functions of a
    :class:`FeatureSnapshot`) - callers (see
    :mod:`app.ml.inference`) are responsible for assembling the
    snapshot from current readings and recent trends.
    """

    def classify(self, snapshot: FeatureSnapshot) -> PollutionClassification:
        """Score every candidate source and normalize into a probability distribution.

        Args:
            snapshot: The current readings + recent trend to evaluate.

        Returns:
            A :class:`PollutionClassification` whose probabilities sum
            to ``1.0`` across every :class:`~app.ml.utils.PollutionSource`
            value (including ``UNKNOWN``, which absorbs whatever
            probability mass no rule explained).
        """
        raw_scores: Dict[PollutionSource, float] = {}
        notes: List[str] = []

        for source, scorer in _RULES:
            score, reason = scorer(snapshot)
            raw_scores[source] = clamp(score, 0.0, MAX_SOURCE_PROBABILITY)
            if reason:
                notes.append(f"{source.value}: {reason}")

        total = sum(raw_scores.values())
        # Whatever probability mass no rule claims goes to UNKNOWN -
        # if every rule scored low (or none fired), UNKNOWN dominates.
        raw_scores[PollutionSource.UNKNOWN] = max(0.0, 1.0 - total) if total < 1.0 else 0.0

        grand_total = sum(raw_scores.values()) or 1.0
        probabilities = {source.value: round(score / grand_total, 4) for source, score in raw_scores.items()}

        # Renormalize after the floor so probabilities still sum to 1.0.
        floored = {k: max(v, MIN_SOURCE_PROBABILITY) for k, v in probabilities.items()}
        floor_total = sum(floored.values())
        probabilities = {k: round(v / floor_total, 4) for k, v in floored.items()}

        most_likely = max(probabilities, key=probabilities.get)

        logger.info(f"Pollution classification: most_likely={most_likely} probabilities={probabilities}")
        return PollutionClassification(probabilities=probabilities, most_likely_source=most_likely, notes=notes)


__all__ = ["PollutionClassifier", "PollutionClassification", "FeatureSnapshot", "MAX_SOURCE_PROBABILITY"]
