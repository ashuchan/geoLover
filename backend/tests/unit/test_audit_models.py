"""Unit tests for Audit module ORM models."""

from __future__ import annotations

import uuid
from datetime import timezone

import pytest

from app.modules.audit.models import (
    AuditRun,
    AuditStatus,
    AuditTrigger,
    Citation,
    CitationMatchType,
    CitationPolarity,
    CompetitorObservation,
    EngineDescriptor,
    EngineHealth,
    QueryExecution,
    QueryExecutionStatus,
    QueryTemplate,
    QueryTemplateSet,
)


class TestQueryTemplateSet:
    def test_defaults(self):
        qts = QueryTemplateSet(slug="test-set", display_name="Test Set")
        assert qts.locale == "en-IN"
        assert qts.is_default is False
        assert qts.id is not None
        assert qts.created_at is not None

    def test_custom_locale(self):
        qts = QueryTemplateSet(slug="s", display_name="S", locale="hi-IN")
        assert qts.locale == "hi-IN"


class TestQueryTemplate:
    def test_defaults(self):
        qt = QueryTemplate(
            template_set_id=uuid.uuid4(),
            template_text="Best {category} in {city}",
        )
        assert qt.priority == 100
        assert qt.required_variables == []
        assert qt.id is not None


class TestEngineDescriptor:
    def test_defaults(self):
        ed = EngineDescriptor(
            slug="openai-v1",
            display_name="ChatGPT",
            provider="openai",
            adapter_class="app.modules.engines.adapters.openai_chat.OpenAIChatAdapter",
        )
        assert ed.health == EngineHealth.healthy
        assert ed.cost_per_query_usd == 0.0
        assert ed.supported_locales == []

    def test_health_enum_values(self):
        assert EngineHealth.healthy.value == "healthy"
        assert EngineHealth.unhealthy.value == "unhealthy"
        assert EngineHealth.degraded.value == "degraded"
        assert EngineHealth.paused.value == "paused"


class TestAuditRun:
    def _make_run(self, **kw):
        defaults = dict(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            trigger=AuditTrigger.manual,
        )
        defaults.update(kw)
        return AuditRun(**defaults)

    def test_defaults(self):
        run = self._make_run()
        assert run.status == AuditStatus.pending
        assert run.queries_total == 0
        assert run.queries_successful == 0
        assert run.queries_cited == 0
        assert run.queries_negative == 0
        assert run.algorithm_version == "v1"
        assert run.id is not None

    def test_trigger_enum(self):
        assert AuditTrigger.manual.value == "manual"
        assert AuditTrigger.weekly.value == "weekly"
        assert AuditTrigger.free_audit.value == "free_audit"

    def test_status_enum(self):
        assert AuditStatus.pending.value == "pending"
        assert AuditStatus.completed.value == "completed"
        assert AuditStatus.failed.value == "failed"
        assert AuditStatus.partial.value == "partial"


class TestQueryExecution:
    def test_defaults(self):
        qe = QueryExecution(
            audit_run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            engine_descriptor_id=uuid.uuid4(),
            query_text="Best dental clinic in Bengaluru",
        )
        assert qe.status == QueryExecutionStatus.pending
        assert qe.id is not None
        assert qe.created_at is not None

    def test_status_enum_values(self):
        assert QueryExecutionStatus.pending.value == "pending"
        assert QueryExecutionStatus.succeeded.value == "succeeded"
        assert QueryExecutionStatus.failed.value == "failed"
        assert QueryExecutionStatus.skipped.value == "skipped"


class TestCitation:
    def test_defaults(self):
        cit = Citation(
            query_execution_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            cited=True,
            confidence=0.99,
        )
        assert cit.polarity == CitationPolarity.neutral
        assert cit.snippet == ""
        assert cit.snippet_start_pos == 0
        assert cit.corroborating_signals == []
        assert cit.algorithm_version == "v1"
        assert cit.id is not None

    def test_polarity_enum(self):
        assert CitationPolarity.positive.value == "positive"
        assert CitationPolarity.negative.value == "negative"
        assert CitationPolarity.neutral.value == "neutral"

    def test_match_type_enum(self):
        assert CitationMatchType.exact_name.value == "exact_name"
        assert CitationMatchType.fuzzy_name.value == "fuzzy_name"
        assert CitationMatchType.composite.value == "composite"


class TestCompetitorObservation:
    def test_defaults(self):
        obs = CompetitorObservation(
            audit_run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            competitor_name="Singh Dental",
            competitor_name_normalized="singh dental",
        )
        assert obs.mention_count == 1
        assert obs.id is not None
