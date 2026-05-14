"""Unit tests for ContentBriefService."""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.exceptions import ConflictError, PermissionDeniedError
from app.modules.content.models import (
    ApprovalFlow,
    BriefState,
    BriefType,
    ContentAsset,
    ContentBrief,
)
from app.modules.content.service import ContentBriefApproved, ContentBriefReady, ContentBriefService


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    return s


def _make_brief(state=BriefState.in_review, tenant_id=None, asset_id=None):
    b = MagicMock(spec=ContentBrief)
    b.id = uuid.uuid4()
    b.tenant_id = tenant_id or uuid.uuid4()
    b.business_id = uuid.uuid4()
    b.current_state = state
    b.current_asset_id = asset_id
    b.approval_flow = ApprovalFlow.agency_only
    b.source_audit_run_id = uuid.uuid4()
    b.brief_type = BriefType.faq_cluster
    b.target_query = "query"
    b.created_at = None
    b.updated_at = None
    return b


def _make_asset():
    a = MagicMock(spec=ContentAsset)
    a.id = uuid.uuid4()
    a.reviewer_notes = None
    a.validation_status = "pending"
    return a


class TestContentBriefServiceApprove:
    @pytest.mark.asyncio
    async def test_approve_success(self):
        tid = uuid.uuid4()
        brief = _make_brief(state=BriefState.in_review, tenant_id=tid)
        session = _make_session()
        svc = ContentBriefService(session)

        with patch.object(svc._brief_repo, "get_by_id", new=AsyncMock(return_value=brief)), \
             patch.object(svc._brief_repo, "update_state", new=AsyncMock(return_value=brief)):

            
            result = await svc.approve_brief(
                brief.id, tenant_id=tid, reviewer_user_id=uuid.uuid4()
            )

        assert len(svc.pending_events) == 1
        assert isinstance(svc.pending_events[0], ContentBriefApproved)

    @pytest.mark.asyncio
    async def test_approve_wrong_tenant(self):
        tid = uuid.uuid4()
        brief = _make_brief(tenant_id=uuid.uuid4())  # different tenant
        session = _make_session()
        svc = ContentBriefService(session)

        with patch.object(svc._brief_repo, "get_by_id", new=AsyncMock(return_value=brief)):
            with pytest.raises(PermissionDeniedError):
                await svc.approve_brief(brief.id, tenant_id=tid, reviewer_user_id=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_approve_invalid_state(self):
        tid = uuid.uuid4()
        brief = _make_brief(state=BriefState.draft, tenant_id=tid)
        session = _make_session()
        svc = ContentBriefService(session)

        with patch.object(svc._brief_repo, "get_by_id", new=AsyncMock(return_value=brief)):
            with pytest.raises(ConflictError):
                await svc.approve_brief(brief.id, tenant_id=tid, reviewer_user_id=uuid.uuid4())


class TestContentBriefServiceReject:
    @pytest.mark.asyncio
    async def test_reject_success(self):
        tid = uuid.uuid4()
        asset = _make_asset()
        brief = _make_brief(state=BriefState.in_review, tenant_id=tid, asset_id=asset.id)
        session = _make_session()
        svc = ContentBriefService(session)

        with patch.object(svc._brief_repo, "get_by_id", new=AsyncMock(return_value=brief)), \
             patch.object(svc._asset_repo, "get_by_id", new=AsyncMock(return_value=asset)), \
             patch.object(svc._brief_repo, "update_state", new=AsyncMock(return_value=brief)):

            result = await svc.reject_brief(
                brief.id,
                tenant_id=tid,
                reviewer_user_id=uuid.uuid4(),
                reviewer_notes="Please revise.",
            )

        assert asset.reviewer_notes == "Please revise."

    @pytest.mark.asyncio
    async def test_reject_wrong_tenant(self):
        brief = _make_brief(state=BriefState.in_review, tenant_id=uuid.uuid4())
        session = _make_session()
        svc = ContentBriefService(session)

        with patch.object(svc._brief_repo, "get_by_id", new=AsyncMock(return_value=brief)):
            with pytest.raises(PermissionDeniedError):
                await svc.reject_brief(
                    brief.id,
                    tenant_id=uuid.uuid4(),
                    reviewer_user_id=uuid.uuid4(),
                    reviewer_notes="",
                )

    @pytest.mark.asyncio
    async def test_reject_approved_brief_fails(self):
        tid = uuid.uuid4()
        brief = _make_brief(state=BriefState.approved, tenant_id=tid)
        session = _make_session()
        svc = ContentBriefService(session)

        with patch.object(svc._brief_repo, "get_by_id", new=AsyncMock(return_value=brief)):
            with pytest.raises(ConflictError):
                await svc.reject_brief(
                    brief.id, tenant_id=tid, reviewer_user_id=uuid.uuid4(), reviewer_notes=""
                )


class TestContentBriefServiceGenerate:
    @pytest.mark.asyncio
    async def test_generate_without_gateway(self):
        session = _make_session()
        svc = ContentBriefService(session, gateway=None)
        tid = uuid.uuid4()
        bid = uuid.uuid4()
        run_id = uuid.uuid4()

        created_brief = _make_brief(state=BriefState.draft, tenant_id=tid)
        created_brief.business_id = bid
        updated_brief = _make_brief(state=BriefState.in_review, tenant_id=tid)
        updated_brief.business_id = bid
        created_asset = _make_asset()

        with patch.object(svc._brief_repo, "create", new=AsyncMock(return_value=created_brief)), \
             patch.object(svc._asset_repo, "create", new=AsyncMock(return_value=created_asset)), \
             patch.object(svc._brief_repo, "update_state", new=AsyncMock(return_value=updated_brief)):

            result = await svc.generate_brief(
                tenant_id=tid,
                business_id=bid,
                source_audit_run_id=run_id,
                brief_type=BriefType.faq_cluster,
                target_query="best dentist Koramangala",
                business_name="Dr. Smith Dental",
                locality="Koramangala",
                city="Bangalore",
            )

        assert result.current_state == BriefState.in_review
        assert len(svc.pending_events) == 1
        assert isinstance(svc.pending_events[0], ContentBriefReady)

    @pytest.mark.asyncio
    async def test_generate_all_brief_types(self):
        session = _make_session()
        for brief_type in BriefType:
            svc = ContentBriefService(session, gateway=None)
            tid, bid = uuid.uuid4(), uuid.uuid4()
            created = _make_brief(state=BriefState.draft, tenant_id=tid)
            created.business_id = bid
            updated = _make_brief(state=BriefState.in_review, tenant_id=tid)
            updated.business_id = bid
            asset = _make_asset()

            with patch.object(svc._brief_repo, "create", new=AsyncMock(return_value=created)), \
                 patch.object(svc._asset_repo, "create", new=AsyncMock(return_value=asset)), \
                 patch.object(svc._brief_repo, "update_state", new=AsyncMock(return_value=updated)):

                result = await svc.generate_brief(
                    tenant_id=tid,
                    business_id=bid,
                    source_audit_run_id=uuid.uuid4(),
                    brief_type=brief_type,
                    target_query="query",
                    business_name="Test Business",
                    locality="Locality",
                    city="City",
                )
            assert result is not None

    def test_static_content_all_brief_types(self):
        for bt in BriefType:
            text = ContentBriefService._static_content(bt, "ACME Corp", "Koramangala", "Bangalore")
            assert "ACME Corp" in text

    def test_to_markdown_faq(self):
        content = {"qas": [{"question": "Q?", "answer": "A."}]}
        md = ContentBriefService._to_markdown(content, BriefType.faq_cluster)
        assert "Q?" in md
        assert "A." in md

    def test_to_markdown_other(self):
        content = {"title": "My Page", "lede": "Short description"}
        md = ContentBriefService._to_markdown(content, BriefType.direct_answer_page)
        assert "My Page" in md
        assert "Short description" in md


class TestStateMachineTransitions:
    def test_valid_transitions(self):
        from app.modules.content.service import _VALID_TRANSITIONS
        assert BriefState.approved in _VALID_TRANSITIONS[BriefState.in_review]
        assert BriefState.rejected in _VALID_TRANSITIONS[BriefState.in_review]
        assert BriefState.published in _VALID_TRANSITIONS[BriefState.approved]
        assert BriefState.in_review in _VALID_TRANSITIONS[BriefState.rejected]
        assert _VALID_TRANSITIONS[BriefState.superseded] == frozenset()

    def test_assert_transition_raises_on_invalid(self):
        svc = ContentBriefService.__new__(ContentBriefService)
        svc._assert_transition(BriefState.draft, BriefState.in_review)  # valid — no raise

        with pytest.raises(ConflictError):
            svc._assert_transition(BriefState.draft, BriefState.approved)  # invalid

    @pytest.mark.asyncio
    async def test_flush_events(self):
        session = _make_session()
        svc = ContentBriefService(session)
        event = ContentBriefReady(brief_id=uuid.uuid4(), tenant_id=uuid.uuid4(), business_id=uuid.uuid4())
        svc._pending_events.append(event)

        with patch("app.modules.content.service.event_bus") as mock_bus:
            mock_bus.publish = AsyncMock()
            await svc.flush_events()
            mock_bus.publish.assert_called_once_with(event)
        assert svc.pending_events == []
