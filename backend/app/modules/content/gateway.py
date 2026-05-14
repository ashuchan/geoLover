"""LLM Gateway - single chokepoint for all LLM calls.

Handles prompt resolution, budget checking, caching, fallback chain,
usage tracking, and audit logging.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import CitedByError
from app.modules.content.models import LLMPurpose
from app.modules.content.providers import (
    AnthropicProvider,
    OpenAIProvider,
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    ProviderSafetyError,
    ProviderTimeoutError,
    StaticTemplateProvider,
)
from app.modules.content.prompt_store import PromptStore
from app.modules.content.repository import (
    LLMCallRepository,
    PromptVersionRepository,
    UsageCounterRepository,
)


class BudgetExceededError(CitedByError):
    error_code = "budget_exceeded"


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_inr: Decimal
    duration_ms: int
    llm_call_id: uuid.UUID
    from_cache: bool = False
    is_fallback: bool = False


# Simple in-memory cache (simulates Redis for testing)
_call_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL_S = 86400 * 30  # 30 days

_MONTHLY_BUDGET_INR = Decimal("5000")  # default per business per month


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class LLMGateway:
    """Single chokepoint for all LLM calls.

    Orchestrates: prompt resolution → budget check → cache → render →
    primary/secondary/static fallback → usage tracking → cache store.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        primary_provider=None,
        secondary_provider=None,
        static_provider=None,
    ) -> None:
        self._session = session
        self._primary = primary_provider or AnthropicProvider()
        self._secondary = secondary_provider or OpenAIProvider()
        self._static = static_provider or StaticTemplateProvider()
        self._prompt_store = PromptStore(session)
        self._llm_call_repo = LLMCallRepository(session)
        self._usage_repo = UsageCounterRepository(session)

    async def complete(
        self,
        *,
        prompt_key: str,
        params: dict,
        tenant_id: uuid.UUID,
        business_id: Optional[uuid.UUID],
        purpose: LLMPurpose,
        locale: str = "en-IN",
        idempotency_key: Optional[str] = None,
    ) -> LLMResult:
        """Single chokepoint for all LLM calls."""
        # 1. Resolve prompt version
        prompt_version = await self._prompt_store.get_active_prompt(prompt_key, locale)

        # 2. Budget pre-check (skip for audit_* purposes)
        if purpose not in (LLMPurpose.audit_quick_wins,) and business_id is not None:
            await self._check_budget(tenant_id, business_id, prompt_version)

        # 3. Cache check
        cache_key = self._make_cache_key(prompt_key, str(prompt_version.id), params, locale)
        if idempotency_key or prompt_version.temperature == 0:
            cached = _call_cache.get(cache_key)
            if cached and (time.time() - cached[1]) < _CACHE_TTL_S:
                llm_call = await self._llm_call_repo.create(
                    tenant_id=tenant_id,
                    business_id=business_id,
                    purpose=purpose,
                    provider="cache",
                    model=prompt_version.recommended_model,
                    prompt_key=prompt_key,
                    prompt_version_id=prompt_version.id,
                    status="cache_hit",
                    cache_key=cache_key,
                    cost_inr=Decimal("0"),
                )
                return LLMResult(
                    text=cached[0],
                    provider="cache",
                    model=prompt_version.recommended_model,
                    input_tokens=0,
                    output_tokens=0,
                    cost_inr=Decimal("0"),
                    duration_ms=0,
                    llm_call_id=llm_call.id,
                    from_cache=True,
                )

        # 4. Render prompt
        system_text, user_text = await self._prompt_store.render_prompt(prompt_version, params)

        # 5. Try primary → secondary → static
        result = await self._call_with_fallback(
            system=system_text,
            user=user_text,
            prompt_version=prompt_version,
            tenant_id=tenant_id,
            business_id=business_id,
            purpose=purpose,
            prompt_key=prompt_key,
            cache_key=cache_key,
        )

        # 6. Update usage counter
        if business_id is not None:
            period = _utcnow().strftime("%Y-%m")
            await self._usage_repo.increment(
                tenant_id,
                business_id,
                period,
                cost_inr=result.cost_inr,
            )

        # 7. Store in cache if deterministic
        if prompt_version.temperature == 0:
            _call_cache[cache_key] = (result.text, time.time())

        return result

    async def _check_budget(
        self,
        tenant_id: uuid.UUID,
        business_id: uuid.UUID,
        prompt_version,
    ) -> None:
        period = _utcnow().strftime("%Y-%m")
        counter = await self._usage_repo.get_or_create(tenant_id, business_id, period)
        estimated = self._primary.estimate_cost(
            prompt_version.max_tokens // 2,
            prompt_version.max_tokens // 2,
            prompt_version.recommended_model,
        )
        if counter.llm_cost_inr + estimated > _MONTHLY_BUDGET_INR:
            raise BudgetExceededError(
                f"Monthly LLM budget exceeded for business {business_id}"
            )

    def _make_cache_key(
        self,
        prompt_key: str,
        version_id: str,
        params: dict,
        locale: str,
    ) -> str:
        canonical = json.dumps(
            {"pk": prompt_key, "vid": version_id, "p": params, "l": locale},
            sort_keys=True,
        )
        return hashlib.sha256(canonical.encode()).hexdigest()[:32]

    async def _call_with_fallback(
        self,
        *,
        system: str,
        user: str,
        prompt_version,
        tenant_id: uuid.UUID,
        business_id: Optional[uuid.UUID],
        purpose: LLMPurpose,
        prompt_key: str,
        cache_key: str,
    ) -> LLMResult:
        # Try primary
        try:
            return await self._call_provider(
                self._primary,
                system=system,
                user=user,
                prompt_version=prompt_version,
                tenant_id=tenant_id,
                business_id=business_id,
                purpose=purpose,
                prompt_key=prompt_key,
                cache_key=cache_key,
                is_fallback=False,
            )
        except (ProviderSafetyError, ProviderAuthError):
            pass  # don't retry, fall through
        except (ProviderRateLimitError, ProviderTimeoutError, ProviderError):
            pass  # fall through after exhausting retries

        # Try secondary
        try:
            return await self._call_provider(
                self._secondary,
                system=system,
                user=user,
                prompt_version=prompt_version,
                tenant_id=tenant_id,
                business_id=business_id,
                purpose=purpose,
                prompt_key=prompt_key,
                cache_key=cache_key,
                is_fallback=True,
            )
        except Exception:
            pass

        # Static fallback (always succeeds)
        return await self._call_provider(
            self._static,
            system=system,
            user=user,
            prompt_version=prompt_version,
            tenant_id=tenant_id,
            business_id=business_id,
            purpose=purpose,
            prompt_key=prompt_key,
            cache_key=cache_key,
            is_fallback=True,
        )

    async def _call_provider(
        self,
        provider,
        *,
        system: str,
        user: str,
        prompt_version,
        tenant_id: uuid.UUID,
        business_id: Optional[uuid.UUID],
        purpose: LLMPurpose,
        prompt_key: str,
        cache_key: str,
        is_fallback: bool,
    ) -> LLMResult:
        start = time.time()
        max_retries = 3 if provider.name == "anthropic" else 1
        last_exc: Optional[Exception] = None

        for attempt in range(max_retries):
            try:
                resp = await provider.call(
                    system=system,
                    user=user,
                    model=prompt_version.recommended_model,
                    temperature=float(prompt_version.temperature),
                    max_tokens=prompt_version.max_tokens,
                    timeout_s=30.0,
                )
                duration_ms = int((time.time() - start) * 1000)
                cost_inr = provider.estimate_cost(
                    resp.input_tokens, resp.output_tokens, resp.model
                )
                llm_call = await self._llm_call_repo.create(
                    tenant_id=tenant_id,
                    business_id=business_id,
                    purpose=purpose,
                    provider=provider.name,
                    model=resp.model,
                    prompt_key=prompt_key,
                    prompt_version_id=prompt_version.id,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    cost_inr=cost_inr,
                    duration_ms=duration_ms,
                    status="success",
                    cache_key=cache_key,
                )
                return LLMResult(
                    text=resp.text,
                    provider=provider.name,
                    model=resp.model,
                    input_tokens=resp.input_tokens,
                    output_tokens=resp.output_tokens,
                    cost_inr=cost_inr,
                    duration_ms=duration_ms,
                    llm_call_id=llm_call.id,
                    from_cache=False,
                    is_fallback=is_fallback,
                )
            except ProviderRateLimitError as e:
                last_exc = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
            except ProviderTimeoutError as e:
                last_exc = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
            except (ProviderSafetyError, ProviderAuthError) as e:
                last_exc = e
                break  # no retry
            except Exception as e:
                last_exc = e
                break

        raise last_exc or ProviderError(f"Provider {provider.name} failed")
