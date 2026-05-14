"""Unit tests for Content module models."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.modules.content.models import (
    ApprovalFlow,
    BriefState,
    BriefType,
    ContentAsset,
    ContentBrief,
    LLMCall,
    LLMPurpose,
    PromptVersion,
    UsageCounter,
)


class TestEnums:
    def test_brief_type_values(self):
        assert BriefType.direct_answer_page.value == "direct_answer_page"
        assert BriefType.faq_cluster.value == "faq_cluster"
        assert BriefType.comparison_page.value == "comparison_page"
        assert BriefType.entity_summary.value == "entity_summary"

    def test_brief_state_values(self):
        assert BriefState.draft.value == "draft"
        assert BriefState.in_review.value == "in_review"
        assert BriefState.approved.value == "approved"
        assert BriefState.rejected.value == "rejected"
        assert BriefState.superseded.value == "superseded"
        assert BriefState.published.value == "published"

    def test_approval_flow_values(self):
        assert ApprovalFlow.agency_only.value == "agency_only"
        assert ApprovalFlow.business_only.value == "business_only"
        assert ApprovalFlow.agency_then_business.value == "agency_then_business"

    def test_llm_purpose_values(self):
        assert LLMPurpose.content_brief_gen.value == "content_brief_gen"
        assert LLMPurpose.audit_quick_wins.value == "audit_quick_wins"
        assert LLMPurpose.pii_redaction.value == "pii_redaction"


class TestPromptVersion:
    def test_defaults(self):
        pv = PromptVersion(
            prompt_key="test_key",
            version=1,
            system_text="You are helpful.",
            user_template="Hello {{name}}",
            recommended_model="claude-sonnet-4-6",
            max_tokens=1000,
        )
        assert pv.temperature == Decimal("0.0")
        assert pv.locale == "en-IN"
        assert pv.active_flag is False
        assert pv.experiment_cohort == "control"
        assert pv.id is not None
        assert pv.created_at is not None

    def test_custom_values(self):
        tid = uuid.uuid4()
        pv = PromptVersion(
            prompt_key="faq_v",
            version=2,
            system_text="System",
            user_template="User",
            recommended_model="claude-opus-4-7",
            max_tokens=2000,
            temperature=Decimal("0.5"),
            locale="hi-IN",
            active_flag=True,
            experiment_cohort="exp_alpha",
            notes="Experiment prompt",
            created_by_user_id=tid,
        )
        assert pv.temperature == Decimal("0.5")
        assert pv.locale == "hi-IN"
        assert pv.active_flag is True
        assert pv.experiment_cohort == "exp_alpha"
        assert pv.notes == "Experiment prompt"
        assert pv.created_by_user_id == tid


class TestContentBrief:
    def test_defaults(self):
        brief = ContentBrief(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            source_audit_run_id=uuid.uuid4(),
            brief_type=BriefType.faq_cluster,
            target_query="best dentist in Koramangala",
            approval_flow=ApprovalFlow.agency_only,
        )
        assert brief.current_state == BriefState.draft
        assert brief.id is not None
        assert brief.created_at is not None
        assert brief.updated_at is not None
        assert brief.deleted_at is None
        assert brief.current_asset_id is None

    def test_custom_state(self):
        brief = ContentBrief(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            source_audit_run_id=uuid.uuid4(),
            brief_type=BriefType.direct_answer_page,
            target_query="q",
            approval_flow=ApprovalFlow.business_only,
            current_state=BriefState.in_review,
        )
        assert brief.current_state == BriefState.in_review


class TestContentAsset:
    def test_defaults(self):
        asset = ContentAsset(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            brief_id=uuid.uuid4(),
            version=1,
            markdown="# Title\n\nBody",
            html="<h1>Title</h1>",
            prompt_version_id=uuid.uuid4(),
            llm_call_id=uuid.uuid4(),
        )
        assert asset.validation_status == "pending"
        assert asset.id is not None
        assert asset.created_at is not None
        assert asset.schema_jsonld is None
        assert asset.reviewer_notes is None


class TestLLMCall:
    def test_defaults(self):
        call = LLMCall(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            purpose=LLMPurpose.content_brief_gen,
            provider="anthropic",
            model="claude-sonnet-4-6",
            prompt_key="direct_answer_page_v",
            status="success",
        )
        assert call.cost_inr == Decimal("0")
        assert call.id is not None
        assert call.created_at is not None


class TestUsageCounter:
    def test_defaults(self):
        uc = UsageCounter(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            period="2026-05",
        )
        assert uc.llm_calls_count == 0
        assert uc.llm_cost_inr == Decimal("0")
        assert uc.content_briefs_generated == 0
        assert uc.updated_at is not None
