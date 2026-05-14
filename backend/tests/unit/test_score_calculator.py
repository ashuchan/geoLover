"""Unit tests for AIVisibilityScoreCalculator."""

from __future__ import annotations

import pytest

from app.modules.audit.score_calculator import (
    AIVisibilityScoreCalculator,
    ConfidenceBand,
    EngineQueryStats,
    ScoreResult,
)


def _stats(engine_id: str, total: int, successful: int, cited: int, negative: int) -> EngineQueryStats:
    return EngineQueryStats(
        engine_id=engine_id,
        queries_total=total,
        queries_successful=successful,
        queries_cited=cited,
        queries_negative=negative,
    )


class TestAIVisibilityScoreCalculator:
    def setup_method(self):
        self.calc = AIVisibilityScoreCalculator()

    def test_zero_citations_returns_zero(self):
        stats = [_stats("openai", 50, 50, 0, 0)]
        result = self.calc.calculate(stats)
        assert result.audit_score == 0.0

    def test_all_cited_returns_100(self):
        stats = [_stats("openai", 50, 50, 50, 0)]
        result = self.calc.calculate(stats)
        assert result.audit_score == 100.0

    def test_negatives_reduce_score(self):
        """Negative citations count half — 50 cited, 10 negative → (50 - 5) / 50 * 100 = 90."""
        stats = [_stats("openai", 50, 50, 50, 10)]
        result = self.calc.calculate(stats)
        assert abs(result.audit_score - 90.0) < 0.01

    def test_score_bounded_at_zero(self):
        """Can't go below 0."""
        stats = [_stats("openai", 10, 10, 0, 20)]  # negative > cited → raw negative
        result = self.calc.calculate(stats)
        assert result.audit_score >= 0.0

    def test_score_bounded_at_100(self):
        stats = [_stats("openai", 10, 10, 10, 0)]
        result = self.calc.calculate(stats)
        assert result.audit_score <= 100.0

    def test_empty_stats_returns_zero(self):
        result = self.calc.calculate([])
        assert result.audit_score == 0.0
        assert result.confidence_band == ConfidenceBand.low

    def test_equal_weight_average(self):
        """Two engines, equal weight average."""
        stats = [
            _stats("openai", 50, 50, 50, 0),   # score = 100
            _stats("perplexity", 50, 50, 0, 0), # score = 0
        ]
        result = self.calc.calculate(stats)
        assert abs(result.audit_score - 50.0) < 0.01

    def test_engine_with_zero_total_excluded(self):
        stats = [
            _stats("openai", 0, 0, 0, 0),  # total=0 → excluded
            _stats("perplexity", 50, 50, 25, 0),  # score = 50
        ]
        result = self.calc.calculate(stats)
        assert abs(result.audit_score - 50.0) < 0.01

    def test_confidence_band_high(self):
        """≥40 successful across ≥2 engines → high."""
        stats = [
            _stats("openai", 30, 30, 10, 0),
            _stats("perplexity", 20, 20, 5, 0),
        ]
        result = self.calc.calculate(stats)
        assert result.confidence_band == ConfidenceBand.high

    def test_confidence_band_medium(self):
        """≥20 successful but only 1 engine → medium."""
        stats = [_stats("openai", 25, 25, 5, 0)]
        result = self.calc.calculate(stats)
        assert result.confidence_band == ConfidenceBand.medium

    def test_confidence_band_low(self):
        """< 20 successful → low."""
        stats = [_stats("openai", 15, 15, 5, 0)]
        result = self.calc.calculate(stats)
        assert result.confidence_band == ConfidenceBand.low

    def test_per_engine_scores_returned(self):
        stats = [
            _stats("openai", 10, 10, 5, 0),     # 50
            _stats("perplexity", 10, 10, 10, 0), # 100
        ]
        result = self.calc.calculate(stats)
        assert "openai" in result.per_engine_scores
        assert "perplexity" in result.per_engine_scores
        assert abs(result.per_engine_scores["openai"] - 50.0) < 0.01
        assert abs(result.per_engine_scores["perplexity"] - 100.0) < 0.01

    def test_determinism(self):
        """Same input always produces same output."""
        stats = [_stats("openai", 50, 40, 20, 5)]
        r1 = self.calc.calculate(stats)
        r2 = self.calc.calculate(stats)
        assert r1.audit_score == r2.audit_score

    def test_partial_citation_rate(self):
        """20 cited out of 50 = 40 base score."""
        stats = [_stats("openai", 50, 50, 20, 0)]
        result = self.calc.calculate(stats)
        assert abs(result.audit_score - 40.0) < 0.01
