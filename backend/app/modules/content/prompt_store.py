"""Prompt store with in-memory cache in front of PromptVersionRepository."""

from __future__ import annotations

import time
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.content.models import PromptVersion
from app.modules.content.repository import PromptVersionRepository
from app.core.exceptions import NotFoundError

# Module-level cache shared across instances
# key → (PromptVersion, timestamp)
_prompt_cache: dict[str, tuple[PromptVersion, float]] = {}

_CACHE_TTL_S = 300  # 5 minutes


class PromptStore:
    """In-memory cache in front of PromptVersionRepository."""

    _CACHE_TTL_S = _CACHE_TTL_S

    def __init__(self, session: AsyncSession) -> None:
        self._repo = PromptVersionRepository(session)

    async def get_active_prompt(
        self,
        prompt_key: str,
        locale: str = "en-IN",
        cohort: str = "control",
    ) -> PromptVersion:
        """Get active prompt version, using cache if fresh."""
        cache_key = f"{prompt_key}:{locale}:{cohort}"
        now = time.time()

        cached = _prompt_cache.get(cache_key)
        if cached is not None:
            pv, inserted_at = cached
            if (now - inserted_at) < _CACHE_TTL_S:
                return pv

        pv = await self._repo.get_active(prompt_key, locale, cohort)
        if pv is None:
            raise NotFoundError(
                f"No active prompt version found for key='{prompt_key}' locale='{locale}' cohort='{cohort}'"
            )
        _prompt_cache[cache_key] = (pv, now)
        return pv

    async def invalidate(self, prompt_key: Optional[str] = None) -> None:
        """Clear cache for a specific key or all keys."""
        if prompt_key is None:
            _prompt_cache.clear()
        else:
            keys_to_remove = [k for k in _prompt_cache if k.startswith(f"{prompt_key}:")]
            for k in keys_to_remove:
                del _prompt_cache[k]

    async def render_prompt(
        self, prompt_version: PromptVersion, params: dict
    ) -> tuple[str, str]:
        """Render system and user texts by substituting {{variable}} placeholders."""
        system = prompt_version.system_text
        user = prompt_version.user_template

        for k, v in params.items():
            placeholder = "{{" + k + "}}"
            system = system.replace(placeholder, str(v))
            user = user.replace(placeholder, str(v))

        return system, user
