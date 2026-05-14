"""Unit tests for Content module repositories."""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

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
from app.modules.content.repository import (
    ContentAssetRepository,
    ContentBriefRepository,
    LLMCallRepository,
    PromptVersionRepository,
    UsageCounterRepository,
)


def _make_session(scalar_result=None, scalars_list=None):
    session = MagicMock()
    session.flush = AsyncMock()
    session.add = MagicMock()

    result = MagicMock()
    result.scalar_one_or_none.return_value = scalar_result
    scalars_mock = MagicMock()
    scalars_mock.all.return_value = scalars_list or []
    result.scalars.return_value = scalars_mock

    session.execute = AsyncMock(return_value=result)
    return session


def _make_prompt_version():
    return PromptVersion(
        prompt_key="test_key",
        version=1,
        system_text="sys",
        user_template="usr",
        recommended_model="claude-sonnet-4-6",
        max_tokens=1000,
    )


def _make_brief():
    return ContentBrief(
        tenant_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        source_audit_run_id=uuid.uuid4(),
        brief_type=BriefType.faq_cluster,
        target_query="query",
        approval_flow=ApprovalFlow.agency_only,
    )


def _make_asset(brief_id=None):
    return ContentAsset(
        tenant_id=uuid.uuid4(),
        business_id=uuid.uuid4(),
        brief_id=brief_id or uuid.uuid4(),
        version=1,
        markdown="# Title",
        html="<h1>Title</h1>",
        prompt_version_id=uuid.uuid4(),
        llm_call_id=uuid.uuid4(),
    )


class TestPromptVersionRepository:
    @pytest.mark.asyncio
    async def test_get_active_found(self):
        pv = _make_prompt_version()
        session = _make_session(scalar_result=pv)
        repo = PromptVersionRepository(session)
        result = await repo.get_active("test_key", "en-IN")
        assert result is pv

    @pytest.mark.asyncio
    async def test_get_active_not_found(self):
        session = _make_session(scalar_result=None)
        repo = PromptVersionRepository(session)
        result = await repo.get_active("missing", "en-IN")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_id_found(self):
        pv = _make_prompt_version()
        session = _make_session(scalar_result=pv)
        repo = PromptVersionRepository(session)
        result = await repo.get_by_id(pv.id)
        assert result is pv

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self):
        from app.core.exceptions import NotFoundError
        session = _make_session(scalar_result=None)
        repo = PromptVersionRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = PromptVersionRepository(session)
        pv = await repo.create(
            prompt_key="key",
            version=1,
            system_text="sys",
            user_template="usr",
            recommended_model="m",
            max_tokens=100,
        )
        assert session.add.called
        assert session.flush.called
        assert pv.prompt_key == "key"

    @pytest.mark.asyncio
    async def test_list_for_key(self):
        pv = _make_prompt_version()
        session = _make_session(scalars_list=[pv])
        repo = PromptVersionRepository(session)
        results = await repo.list_for_key("test_key")
        assert len(results) == 1


class TestContentBriefRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_found(self):
        brief = _make_brief()
        session = _make_session(scalar_result=brief)
        repo = ContentBriefRepository(session)
        result = await repo.get_by_id(brief.id)
        assert result is brief

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self):
        from app.core.exceptions import NotFoundError
        session = _make_session(scalar_result=None)
        repo = ContentBriefRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_list_for_business(self):
        brief = _make_brief()
        session = _make_session(scalars_list=[brief])
        repo = ContentBriefRepository(session)
        results = await repo.list_for_business(brief.business_id, brief.tenant_id)
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = ContentBriefRepository(session)
        brief = await repo.create(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            source_audit_run_id=uuid.uuid4(),
            brief_type=BriefType.entity_summary,
            target_query="q",
            approval_flow=ApprovalFlow.business_only,
        )
        assert session.add.called
        assert brief.current_state == BriefState.draft

    @pytest.mark.asyncio
    async def test_update_state(self):
        brief = _make_brief()
        asset_id = uuid.uuid4()
        session = _make_session(scalar_result=brief)
        repo = ContentBriefRepository(session)
        result = await repo.update_state(
            brief.id, BriefState.in_review, current_asset_id=asset_id
        )
        assert result.current_state == BriefState.in_review
        assert result.current_asset_id == asset_id

    @pytest.mark.asyncio
    async def test_soft_delete(self):
        brief = _make_brief()
        session = _make_session(scalar_result=brief)
        repo = ContentBriefRepository(session)
        result = await repo.soft_delete(brief.id)
        assert result.deleted_at is not None


class TestContentAssetRepository:
    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self):
        from app.core.exceptions import NotFoundError
        session = _make_session(scalar_result=None)
        repo = ContentAssetRepository(session)
        with pytest.raises(NotFoundError):
            await repo.get_by_id(uuid.uuid4())

    @pytest.mark.asyncio
    async def test_get_latest_for_brief(self):
        asset = _make_asset()
        session = _make_session(scalar_result=asset)
        repo = ContentAssetRepository(session)
        result = await repo.get_latest_for_brief(asset.brief_id)
        assert result is asset

    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = ContentAssetRepository(session)
        asset = await repo.create(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            brief_id=uuid.uuid4(),
            version=1,
            markdown="# Title",
            html="<h1>Title</h1>",
            prompt_version_id=uuid.uuid4(),
            llm_call_id=uuid.uuid4(),
        )
        assert asset.validation_status == "pending"

    @pytest.mark.asyncio
    async def test_update_validation(self):
        asset = _make_asset()
        asset.validation_status = "pending"
        session = _make_session(scalar_result=asset)
        repo = ContentAssetRepository(session)
        result = await repo.update_validation(
            asset.id, status="passed", findings={"ok": True}
        )
        assert result.validation_status == "passed"
        assert result.validation_findings == {"ok": True}


class TestLLMCallRepository:
    @pytest.mark.asyncio
    async def test_create(self):
        session = _make_session()
        repo = LLMCallRepository(session)
        call = await repo.create(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            purpose=LLMPurpose.content_brief_gen,
            provider="anthropic",
            model="claude-sonnet-4-6",
            prompt_key="test",
            status="success",
        )
        assert call.cost_inr == Decimal("0")
        assert session.add.called

    @pytest.mark.asyncio
    async def test_list_for_business(self):
        call = LLMCall(
            tenant_id=uuid.uuid4(),
            business_id=uuid.uuid4(),
            purpose=LLMPurpose.audit_quick_wins,
            provider="cache",
            model="m",
            prompt_key="k",
            status="cache_hit",
        )
        session = _make_session(scalars_list=[call])
        repo = LLMCallRepository(session)
        results = await repo.list_for_business(call.business_id, call.tenant_id)
        assert len(results) == 1


class TestUsageCounterRepository:
    @pytest.mark.asyncio
    async def test_get_or_create_existing(self):
        uc = UsageCounter(tenant_id=uuid.uuid4(), business_id=uuid.uuid4(), period="2026-05")
        session = _make_session(scalar_result=uc)
        repo = UsageCounterRepository(session)
        result = await repo.get_or_create(uc.tenant_id, uc.business_id, "2026-05")
        assert result is uc
        assert not session.add.called

    @pytest.mark.asyncio
    async def test_get_or_create_new(self):
        session = _make_session(scalar_result=None)
        repo = UsageCounterRepository(session)
        tid = uuid.uuid4()
        bid = uuid.uuid4()
        result = await repo.get_or_create(tid, bid, "2026-05")
        assert result.tenant_id == tid
        assert result.period == "2026-05"
        assert session.add.called

    @pytest.mark.asyncio
    async def test_increment(self):
        session = _make_session()
        repo = UsageCounterRepository(session)
        # Should not raise
        await repo.increment(uuid.uuid4(), uuid.uuid4(), "2026-05", cost_inr=Decimal("1.5"))
        assert session.execute.called
