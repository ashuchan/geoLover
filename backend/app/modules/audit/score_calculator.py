"""AIVisibilityScoreCalculator — computes the AI visibility score for an audit.

Formula:
    engine_score_e = ((queries_cited - 0.5 * queries_negative) / queries_total) * 100
    audit_score = weighted_average(engine_score_e, weight=1 for each engine)

Bounded to [0, 100].

Confidence bands:
- high:   ≥40 successful queries across ≥2 engines
- medium: ≥20 successful queries across ≥1 engine
- low:    otherwise
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ConfidenceBand(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


@dataclass(frozen=True)
class EngineQueryStats:
    """Stats for a single engine within an audit."""

    engine_id: str  # slug or UUID str
    queries_total: int
    queries_successful: int
    queries_cited: int
    queries_negative: int


@dataclass(frozen=True)
class ScoreResult:
    audit_score: float
    confidence_band: ConfidenceBand
    per_engine_scores: dict[str, float]


class AIVisibilityScoreCalculator:
    """Calculates AI Visibility Score from per-engine query statistics."""

    def calculate(self, engine_stats: list[EngineQueryStats]) -> ScoreResult:
        """Compute the audit score.

        Args:
            engine_stats: one entry per engine that participated.

        Returns:
            ScoreResult with bounded audit_score, confidence_band, per_engine_scores.
        """
        if not engine_stats:
            return ScoreResult(
                audit_score=0.0,
                confidence_band=ConfidenceBand.low,
                per_engine_scores={},
            )

        per_engine: dict[str, float] = {}
        valid_scores: list[float] = []

        for stats in engine_stats:
            if stats.queries_total <= 0:
                continue
            raw = (
                (stats.queries_cited - 0.5 * stats.queries_negative)
                / stats.queries_total
            ) * 100
            score = max(0.0, min(100.0, raw))
            per_engine[stats.engine_id] = score
            valid_scores.append(score)

        if not valid_scores:
            return ScoreResult(
                audit_score=0.0,
                confidence_band=ConfidenceBand.low,
                per_engine_scores=per_engine,
            )

        # Equal-weight average
        audit_score = sum(valid_scores) / len(valid_scores)
        audit_score = max(0.0, min(100.0, audit_score))

        confidence_band = self._confidence_band(engine_stats)

        return ScoreResult(
            audit_score=round(audit_score, 4),
            confidence_band=confidence_band,
            per_engine_scores=per_engine,
        )

    def _confidence_band(self, engine_stats: list[EngineQueryStats]) -> ConfidenceBand:
        total_successful = sum(s.queries_successful for s in engine_stats)
        engines_with_data = sum(1 for s in engine_stats if s.queries_successful > 0)

        if total_successful >= 40 and engines_with_data >= 2:
            return ConfidenceBand.high
        if total_successful >= 20 and engines_with_data >= 1:
            return ConfidenceBand.medium
        return ConfidenceBand.low
