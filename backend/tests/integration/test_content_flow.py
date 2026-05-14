"""Integration tests — content module: ContentBrief and ContentAsset lifecycle."""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.models import ApprovalFlow, BriefState, BriefType, LLMPurpose
from app.modules.content.repository import (
    ContentAssetRepository,
    ContentBriefRepository,
    LLMCallRepository,
    PromptVersionRepository,
)
from tests.integration.conftest import make_audit_run, make_business, make_category, make_tenant

# Skip entire module if testcontainers not available
pytest.importorskip("testcontainers", reason="testcontainers required for integration tests")

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.asyncio
async def test_content_brief_state_transitions(pg_session: AsyncSession) -> None:
    """Full brief lifecycle: create → in_review → approved via real DB."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = ContentBriefRepository(pg_session)

    brief = await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        source_audit_run_id=run.id,
        brief_type=BriefType.direct_answer_page,
        target_query="best bakery near me",
        approval_flow=ApprovalFlow.agency_only,
    )
    assert brief.current_state == BriefState.draft
    assert brief.business_id == biz.id

    # Transition to in_review
    await repo.update_state(brief.id, BriefState.in_review)
    fetched = await repo.get_by_id(brief.id)
    assert fetched.current_state == BriefState.in_review

    # Transition to approved
    await repo.update_state(brief.id, BriefState.approved)
    fetched = await repo.get_by_id(brief.id)
    assert fetched.current_state == BriefState.approved


@pytest.mark.integration
@pytest.mark.asyncio
async def test_list_briefs_for_business(pg_session: AsyncSession) -> None:
    """list_for_business returns only briefs for the given business."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = ContentBriefRepository(pg_session)

    await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        source_audit_run_id=run.id,
        brief_type=BriefType.faq_cluster,
        target_query="top pastry shops",
        approval_flow=ApprovalFlow.agency_only,
    )
    await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        source_audit_run_id=run.id,
        brief_type=BriefType.comparison_page,
        target_query="bakery vs cafe",
        approval_flow=ApprovalFlow.agency_only,
    )

    briefs = await repo.list_for_business(biz.id, tenant.id)
    assert len(briefs) == 2
    types = {b.brief_type for b in briefs}
    assert BriefType.faq_cluster in types
    assert BriefType.comparison_page in types


@pytest.mark.integration
@pytest.mark.asyncio
async def test_create_brief_with_different_types(pg_session: AsyncSession) -> None:
    """ContentBrief can be created for each BriefType without error."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = ContentBriefRepository(pg_session)

    for btype in [
        BriefType.direct_answer_page,
        BriefType.faq_cluster,
        BriefType.comparison_page,
        BriefType.entity_summary,
    ]:
        brief = await repo.create(
            tenant_id=tenant.id,
            business_id=biz.id,
            source_audit_run_id=run.id,
            brief_type=btype,
            target_query=f"query for {btype.value}",
            approval_flow=ApprovalFlow.agency_only,
        )
        assert brief.brief_type == btype

    all_briefs = await repo.list_for_business(biz.id, tenant.id)
    assert len(all_briefs) == 4


@pytest.mark.integration
@pytest.mark.asyncio
async def test_brief_soft_delete_hides_from_list(pg_session: AsyncSession) -> None:
    """Soft-deleted brief no longer appears in list_for_business."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    repo = ContentBriefRepository(pg_session)

    brief = await repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        source_audit_run_id=run.id,
        brief_type=BriefType.entity_summary,
        target_query="who is test bakery",
        approval_flow=ApprovalFlow.business_only,
    )

    await repo.soft_delete(brief.id)

    briefs = await repo.list_for_business(biz.id, tenant.id)
    assert not any(b.id == brief.id for b in briefs)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_content_asset_creation_and_retrieval(pg_session: AsyncSession) -> None:
    """ContentAsset can be created and retrieved for a brief."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)
    run = await make_audit_run(pg_session, tenant=tenant, business=biz)

    brief_repo = ContentBriefRepository(pg_session)
    brief = await brief_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        source_audit_run_id=run.id,
        brief_type=BriefType.direct_answer_page,
        target_query="best bakery in Koramangala",
        approval_flow=ApprovalFlow.agency_only,
    )

    # Create a PromptVersion first (required FK)
    pv_repo = PromptVersionRepository(pg_session)
    pv = await pv_repo.create(
        prompt_key="content_gen_v1",
        version=1,
        system_text="You are a content writer.",
        user_template="Write about {topic}",
        recommended_model="claude-3-haiku",
        max_tokens=1024,
    )

    # Create an LLMCall
    llm_repo = LLMCallRepository(pg_session)
    llm_call = await llm_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        purpose=LLMPurpose.content_brief_gen,
        provider="anthropic",
        model="claude-3-haiku",
        prompt_key="content_gen_v1",
        prompt_version_id=pv.id,
    )

    # Create the ContentAsset
    asset_repo = ContentAssetRepository(pg_session)
    asset = await asset_repo.create(
        tenant_id=tenant.id,
        business_id=biz.id,
        brief_id=brief.id,
        version=1,
        markdown="# Best Bakery\nThis is a great bakery.",
        html="<h1>Best Bakery</h1><p>This is a great bakery.</p>",
        prompt_version_id=pv.id,
        llm_call_id=llm_call.id,
    )
    assert asset.brief_id == brief.id
    assert asset.version == 1
    assert asset.validation_status == "pending"

    latest = await asset_repo.get_latest_for_brief(brief.id)
    assert latest is not None
    assert latest.id == asset.id


@pytest.mark.integration
@pytest.mark.asyncio
async def test_llm_call_list_for_business(pg_session: AsyncSession) -> None:
    """LLMCallRepository.list_for_business returns correct records."""
    tenant = await make_tenant(pg_session, slug=f"t-{uuid.uuid4().hex[:8]}")
    cat = await make_category(pg_session, slug=f"c-{uuid.uuid4().hex[:8]}")
    biz = await make_business(pg_session, tenant=tenant, category=cat)

    repo = LLMCallRepository(pg_session)

    for purpose in [LLMPurpose.content_brief_gen, LLMPurpose.audit_quick_wins]:
        await repo.create(
            tenant_id=tenant.id,
            business_id=biz.id,
            purpose=purpose,
            provider="anthropic",
            model="claude-3-haiku",
            prompt_key="some_key",
            cost_inr=Decimal("0.05"),
        )

    calls = await repo.list_for_business(biz.id, tenant.id)
    assert len(calls) == 2
