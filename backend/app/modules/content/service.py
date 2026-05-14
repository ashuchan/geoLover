"""ContentBriefService — orchestrates content brief lifecycle."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, event_bus
from app.core.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.modules.content.gateway import LLMGateway
from app.modules.content.models import (
    ApprovalFlow,
    BriefState,
    BriefType,
    ContentBrief,
    LLMPurpose,
)
from app.modules.content.repository import (
    ContentAssetRepository,
    ContentBriefRepository,
    PromptVersionRepository,
)
from app.modules.content.validators import ContentValidator


_BRIEF_TYPE_PROMPT_KEY: dict[BriefType, str] = {
    BriefType.direct_answer_page: "direct_answer_page_v",
    BriefType.faq_cluster: "faq_cluster_v",
    BriefType.comparison_page: "comparison_page_v",
    BriefType.entity_summary: "entity_summary_v",
}

_VALID_TRANSITIONS: dict[BriefState, frozenset[BriefState]] = {
    BriefState.draft: frozenset({BriefState.in_review, BriefState.superseded}),
    BriefState.in_review: frozenset({BriefState.approved, BriefState.rejected, BriefState.superseded}),
    BriefState.approved: frozenset({BriefState.published, BriefState.superseded}),
    BriefState.rejected: frozenset({BriefState.in_review, BriefState.superseded}),
    BriefState.superseded: frozenset(),
    BriefState.published: frozenset({BriefState.superseded}),
}


@dataclass(frozen=True)
class ContentBriefReady(DomainEvent):
    brief_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)
    business_id: uuid.UUID = uuid.UUID(int=0)


@dataclass(frozen=True)
class ContentBriefApproved(DomainEvent):
    brief_id: uuid.UUID = uuid.UUID(int=0)
    tenant_id: uuid.UUID = uuid.UUID(int=0)
    business_id: uuid.UUID = uuid.UUID(int=0)


class ContentBriefService:
    """Manages content brief lifecycle: generate, approve, reject."""

    def __init__(self, session: AsyncSession, *, gateway: Optional[LLMGateway] = None) -> None:
        self._session = session
        self._brief_repo = ContentBriefRepository(session)
        self._asset_repo = ContentAssetRepository(session)
        self._gateway = gateway
        self._pending_events: list[DomainEvent] = []

    @property
    def pending_events(self) -> list[DomainEvent]:
        return list(self._pending_events)

    async def flush_events(self) -> None:
        for event in self._pending_events:
            await event_bus.publish(event)
        self._pending_events.clear()

    async def get_brief(self, brief_id: uuid.UUID) -> ContentBrief:
        return await self._brief_repo.get_by_id(brief_id)

    async def list_briefs(
        self,
        business_id: uuid.UUID,
        tenant_id: uuid.UUID,
        *,
        state: Optional[BriefState] = None,
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[ContentBrief]:
        return await self._brief_repo.list_for_business(
            business_id, tenant_id, state=state, limit=limit, offset=offset
        )

    def _assert_transition(self, current: BriefState, target: BriefState) -> None:
        allowed = _VALID_TRANSITIONS.get(current, frozenset())
        if target not in allowed:
            raise ConflictError(
                f"Cannot transition brief from '{current.value}' to '{target.value}'"
            )

    async def approve_brief(
        self,
        brief_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        reviewer_user_id: uuid.UUID,
    ) -> ContentBrief:
        brief = await self._brief_repo.get_by_id(brief_id)
        if brief.tenant_id != tenant_id:
            raise PermissionDeniedError("Brief does not belong to this tenant")
        self._assert_transition(brief.current_state, BriefState.approved)

        brief = await self._brief_repo.update_state(
            brief_id,
            BriefState.approved,
            reviewer_user_id=reviewer_user_id,
        )
        self._pending_events.append(
            ContentBriefApproved(
                brief_id=brief.id,
                tenant_id=tenant_id,
                business_id=brief.business_id,
            )
        )
        return brief

    async def reject_brief(
        self,
        brief_id: uuid.UUID,
        *,
        tenant_id: uuid.UUID,
        reviewer_user_id: uuid.UUID,
        reviewer_notes: str,
    ) -> ContentBrief:
        brief = await self._brief_repo.get_by_id(brief_id)
        if brief.tenant_id != tenant_id:
            raise PermissionDeniedError("Brief does not belong to this tenant")
        self._assert_transition(brief.current_state, BriefState.rejected)

        if brief.current_asset_id is not None:
            asset = await self._asset_repo.get_by_id(brief.current_asset_id)
            asset.reviewer_notes = reviewer_notes
            await self._session.flush()

        return await self._brief_repo.update_state(
            brief_id,
            BriefState.rejected,
            reviewer_user_id=reviewer_user_id,
        )

    async def generate_brief(
        self,
        *,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        source_audit_run_id: uuid.UUID,
        source_lost_query_ids: Optional[list] = None,
        brief_type: BriefType,
        target_query: str,
        approval_flow: ApprovalFlow = ApprovalFlow.agency_only,
        business_name: str = "",
        locality: str = "",
        city: str = "",
    ) -> ContentBrief:
        brief = await self._brief_repo.create(
            tenant_id=tenant_id,
            business_id=business_id,
            source_audit_run_id=source_audit_run_id,
            brief_type=brief_type,
            target_query=target_query,
            approval_flow=approval_flow,
            source_lost_query_ids=source_lost_query_ids,
        )

        prompt_key = _BRIEF_TYPE_PROMPT_KEY[brief_type]
        params = {
            "business_name": business_name,
            "locality": locality,
            "city": city,
            "target_query": target_query,
            "brief_type": brief_type.value,
        }

        if self._gateway is not None:
            try:
                llm_result = await self._gateway.complete(
                    prompt_key=prompt_key,
                    params=params,
                    tenant_id=tenant_id,
                    business_id=business_id,
                    purpose=LLMPurpose.content_brief_gen,
                )
                raw_text = llm_result.text
                llm_call_id = llm_result.llm_call_id
                prompt_version_id = await self._resolve_prompt_version_id(prompt_key)
            except Exception:
                raw_text = self._static_content(brief_type, business_name, locality, city)
                llm_call_id = uuid.UUID(int=0)
                prompt_version_id = uuid.UUID(int=0)
        else:
            raw_text = self._static_content(brief_type, business_name, locality, city)
            llm_call_id = uuid.UUID(int=0)
            prompt_version_id = uuid.UUID(int=0)

        try:
            content = json.loads(raw_text) if isinstance(raw_text, str) else raw_text
        except (json.JSONDecodeError, ValueError):
            content = {"text": raw_text}

        schema_jsonld = content.pop("jsonld", None) if isinstance(content, dict) else None
        markdown = self._to_markdown(content, brief_type)
        html = f"<article>{markdown}</article>"

        validator = ContentValidator()
        val_result = validator.validate(
            content,
            brief_type=brief_type.value,
            output_schema={},
            business_name=business_name,
            locality=locality,
            city=city,
            schema_jsonld=schema_jsonld,
        )

        asset = await self._asset_repo.create(
            tenant_id=tenant_id,
            business_id=business_id,
            brief_id=brief.id,
            version=1,
            markdown=markdown,
            html=html,
            schema_jsonld=schema_jsonld,
            prompt_version_id=prompt_version_id,
            llm_call_id=llm_call_id,
            validation_status="passed" if val_result.passed else "failed",
            validation_findings={"findings": val_result.findings} if val_result.findings else None,
        )

        brief = await self._brief_repo.update_state(
            brief.id,
            BriefState.in_review,
            current_asset_id=asset.id,
        )

        self._pending_events.append(
            ContentBriefReady(
                brief_id=brief.id,
                tenant_id=tenant_id,
                business_id=business_id,
            )
        )
        return brief

    async def _resolve_prompt_version_id(self, prompt_key: str) -> uuid.UUID:
        repo = PromptVersionRepository(self._session)
        pv = await repo.get_active(prompt_key, "en-IN")
        return pv.id if pv else uuid.UUID(int=0)

    @staticmethod
    def _static_content(
        brief_type: BriefType,
        business_name: str,
        locality: str,
        city: str,
    ) -> str:
        loc = f"{locality}, {city}".strip(", ") if locality or city else city
        name = business_name or "Your Business"
        templates: dict[str, dict] = {
            BriefType.direct_answer_page.value: {
                "title": f"{name} — Direct Answer",
                "h1": f"{name} in {loc}",
                "lede": f"{name} is a professional service provider in {loc}.",
                "body_sections": [],
                "faq_pairs": [],
                "jsonld": {"@type": "Service", "@context": "https://schema.org"},
            },
            BriefType.faq_cluster.value: {
                "qas": [
                    {"question": f"What does {name} offer?", "answer": f"{name} in {loc} offers a range of professional services."},
                    {"question": f"Where is {name} located?", "answer": f"{name} is located in {loc}."},
                    {"question": "How can I contact them?", "answer": "Please visit the website for contact details."},
                    {"question": "What are the business hours?", "answer": "Standard business hours apply."},
                    {"question": "Do they offer consultations?", "answer": "Yes, initial consultations are available."},
                ]
            },
            BriefType.comparison_page.value: {
                "title": f"Choosing a Provider like {name} in {loc}",
                "criteria": [],
                "comparison_table": [],
                "jsonld": {"@type": "WebPage", "@context": "https://schema.org"},
            },
            BriefType.entity_summary.value: {
                "description": f"{name} is a trusted service provider in {loc}.",
                "services": [],
                "audience": f"Residents and businesses in {loc}",
                "jsonld": {"@type": "LocalBusiness", "@context": "https://schema.org"},
            },
        }
        return json.dumps(templates.get(brief_type.value, {"title": name, "body": f"{name} in {loc}."}))

    @staticmethod
    def _to_markdown(content: dict, brief_type: BriefType) -> str:
        if brief_type == BriefType.faq_cluster:
            qas = content.get("qas", [])
            lines = [
                f"**Q: {qa.get('question', '')}**\n\nA: {qa.get('answer', '')}\n"
                for qa in qas
            ]
            return "\n".join(lines)
        title = content.get("title") or content.get("h1") or ""
        lede = content.get("lede") or content.get("description") or ""
        return f"# {title}\n\n{lede}"
