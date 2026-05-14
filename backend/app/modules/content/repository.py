"""Repository layer for the Content module."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.modules.content.models import (
    BriefState,
    BriefType,
    ApprovalFlow,
    ContentAsset,
    ContentBrief,
    LLMCall,
    LLMPurpose,
    PromptVersion,
    UsageCounter,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PromptVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active(
        self,
        prompt_key: str,
        locale: str,
        cohort: str = "control",
    ) -> Optional[PromptVersion]:
        result = await self._session.execute(
            select(PromptVersion)
            .where(
                PromptVersion.prompt_key == prompt_key,
                PromptVersion.locale == locale,
                PromptVersion.experiment_cohort == cohort,
                PromptVersion.active_flag.is_(True),
                PromptVersion.retired_at.is_(None),
            )
            .order_by(PromptVersion.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, id: uuid.UUID) -> PromptVersion:
        result = await self._session.execute(
            select(PromptVersion).where(PromptVersion.id == id)
        )
        pv = result.scalar_one_or_none()
        if pv is None:
            raise NotFoundError(f"PromptVersion {id} not found")
        return pv

    async def create(
        self,
        *,
        prompt_key: str,
        version: int,
        system_text: str,
        user_template: str,
        recommended_model: str,
        max_tokens: int,
        temperature: Decimal = Decimal("0.0"),
        locale: str = "en-IN",
        active_flag: bool = False,
        experiment_cohort: str = "control",
        parameters_schema: Optional[dict] = None,
        output_schema: Optional[dict] = None,
        notes: Optional[str] = None,
        created_by_user_id: Optional[uuid.UUID] = None,
    ) -> PromptVersion:
        pv = PromptVersion(
            prompt_key=prompt_key,
            version=version,
            system_text=system_text,
            user_template=user_template,
            recommended_model=recommended_model,
            max_tokens=max_tokens,
            temperature=temperature,
            locale=locale,
            active_flag=active_flag,
            experiment_cohort=experiment_cohort,
            parameters_schema=parameters_schema,
            output_schema=output_schema,
            notes=notes,
            created_by_user_id=created_by_user_id,
        )
        self._session.add(pv)
        await self._session.flush()
        return pv

    async def list_for_key(self, prompt_key: str) -> Sequence[PromptVersion]:
        result = await self._session.execute(
            select(PromptVersion)
            .where(PromptVersion.prompt_key == prompt_key)
            .order_by(PromptVersion.version.desc())
        )
        return result.scalars().all()


class ContentBriefRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: uuid.UUID) -> ContentBrief:
        result = await self._session.execute(
            select(ContentBrief).where(
                ContentBrief.id == id,
                ContentBrief.deleted_at.is_(None),
            )
        )
        brief = result.scalar_one_or_none()
        if brief is None:
            raise NotFoundError(f"ContentBrief {id} not found")
        return brief

    async def list_for_business(
        self,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        state: Optional[BriefState] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[ContentBrief]:
        stmt = (
            select(ContentBrief)
            .where(
                ContentBrief.business_id == business_id,
                ContentBrief.tenant_id == tenant_id,
                ContentBrief.deleted_at.is_(None),
            )
            .order_by(ContentBrief.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        if state is not None:
            stmt = stmt.where(ContentBrief.current_state == state)
        result = await self._session.execute(stmt)
        return result.scalars().all()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        source_audit_run_id: uuid.UUID,
        brief_type: BriefType,
        target_query: str,
        approval_flow: ApprovalFlow,
        source_lost_query_ids: Optional[list] = None,
        reviewer_user_id: Optional[uuid.UUID] = None,
    ) -> ContentBrief:
        brief = ContentBrief(
            tenant_id=tenant_id,
            business_id=business_id,
            source_audit_run_id=source_audit_run_id,
            brief_type=brief_type,
            target_query=target_query,
            approval_flow=approval_flow,
            source_lost_query_ids=source_lost_query_ids,
            reviewer_user_id=reviewer_user_id,
        )
        self._session.add(brief)
        await self._session.flush()
        return brief

    async def update_state(
        self,
        brief_id: uuid.UUID,
        new_state: BriefState,
        *,
        current_asset_id: Optional[uuid.UUID] = None,
        reviewer_user_id: Optional[uuid.UUID] = None,
    ) -> ContentBrief:
        brief = await self.get_by_id(brief_id)
        brief.current_state = new_state
        brief.updated_at = _utcnow()
        if current_asset_id is not None:
            brief.current_asset_id = current_asset_id
        if reviewer_user_id is not None:
            brief.reviewer_user_id = reviewer_user_id
        await self._session.flush()
        return brief

    async def soft_delete(self, brief_id: uuid.UUID) -> ContentBrief:
        brief = await self.get_by_id(brief_id)
        brief.deleted_at = _utcnow()
        brief.updated_at = _utcnow()
        await self._session.flush()
        return brief


class ContentAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, id: uuid.UUID) -> ContentAsset:
        result = await self._session.execute(
            select(ContentAsset).where(ContentAsset.id == id)
        )
        asset = result.scalar_one_or_none()
        if asset is None:
            raise NotFoundError(f"ContentAsset {id} not found")
        return asset

    async def get_latest_for_brief(self, brief_id: uuid.UUID) -> Optional[ContentAsset]:
        result = await self._session.execute(
            select(ContentAsset)
            .where(ContentAsset.brief_id == brief_id)
            .order_by(ContentAsset.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_brief(self, brief_id: uuid.UUID) -> Sequence[ContentAsset]:
        result = await self._session.execute(
            select(ContentAsset)
            .where(ContentAsset.brief_id == brief_id)
            .order_by(ContentAsset.version.desc())
        )
        return result.scalars().all()

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        brief_id: uuid.UUID,
        version: int,
        markdown: str,
        html: str,
        prompt_version_id: uuid.UUID,
        llm_call_id: uuid.UUID,
        schema_jsonld: Optional[dict] = None,
        validation_status: str = "pending",
        validation_findings: Optional[dict] = None,
        reviewer_notes: Optional[str] = None,
    ) -> ContentAsset:
        asset = ContentAsset(
            tenant_id=tenant_id,
            business_id=business_id,
            brief_id=brief_id,
            version=version,
            markdown=markdown,
            html=html,
            prompt_version_id=prompt_version_id,
            llm_call_id=llm_call_id,
            schema_jsonld=schema_jsonld,
            validation_status=validation_status,
            validation_findings=validation_findings,
            reviewer_notes=reviewer_notes,
        )
        self._session.add(asset)
        await self._session.flush()
        return asset

    async def update_validation(
        self,
        asset_id: uuid.UUID,
        *,
        status: str,
        findings: Optional[dict] = None,
    ) -> ContentAsset:
        asset = await self.get_by_id(asset_id)
        asset.validation_status = status
        if findings is not None:
            asset.validation_findings = findings
        await self._session.flush()
        return asset


class LLMCallRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: Optional[uuid.UUID],
        purpose: LLMPurpose,
        provider: str,
        model: str,
        prompt_key: str,
        prompt_version_id: Optional[uuid.UUID] = None,
        input_tokens: Optional[int] = None,
        output_tokens: Optional[int] = None,
        cost_inr: Decimal = Decimal("0"),
        duration_ms: Optional[int] = None,
        status: str = "success",
        cache_key: Optional[str] = None,
        workflow_id: Optional[str] = None,
        error_class: Optional[str] = None,
    ) -> LLMCall:
        call = LLMCall(
            tenant_id=tenant_id,
            business_id=business_id,
            purpose=purpose,
            provider=provider,
            model=model,
            prompt_key=prompt_key,
            prompt_version_id=prompt_version_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_inr=cost_inr,
            duration_ms=duration_ms,
            status=status,
            cache_key=cache_key,
            workflow_id=workflow_id,
            error_class=error_class,
        )
        self._session.add(call)
        await self._session.flush()
        return call

    async def list_for_business(
        self,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        limit: int = 50,
    ) -> Sequence[LLMCall]:
        result = await self._session.execute(
            select(LLMCall)
            .where(
                LLMCall.business_id == business_id,
                LLMCall.tenant_id == tenant_id,
            )
            .order_by(LLMCall.created_at.desc())
            .limit(limit)
        )
        return result.scalars().all()


class UsageCounterRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(
        self,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        period: str,
    ) -> UsageCounter:
        result = await self._session.execute(
            select(UsageCounter).where(
                UsageCounter.tenant_id == tenant_id,
                UsageCounter.business_id == business_id,
                UsageCounter.period == period,
            )
        )
        counter = result.scalar_one_or_none()
        if counter is None:
            counter = UsageCounter(
                tenant_id=tenant_id,
                business_id=business_id,
                period=period,
            )
            self._session.add(counter)
            await self._session.flush()
        return counter

    async def increment(
        self,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        period: str,
        *,
        cost_inr: Decimal,
        briefs_delta: int = 0,
    ) -> None:
        stmt = (
            pg_insert(UsageCounter)
            .values(
                tenant_id=tenant_id,
                business_id=business_id,
                period=period,
                llm_calls_count=1,
                llm_cost_inr=cost_inr,
                content_briefs_generated=briefs_delta,
                updated_at=_utcnow(),
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "business_id", "period"],
                set_={
                    "llm_calls_count": UsageCounter.llm_calls_count + 1,
                    "llm_cost_inr": UsageCounter.llm_cost_inr + cost_inr,
                    "content_briefs_generated": UsageCounter.content_briefs_generated + briefs_delta,
                    "updated_at": _utcnow(),
                },
            )
        )
        await self._session.execute(stmt)
