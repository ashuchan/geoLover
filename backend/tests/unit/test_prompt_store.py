"""Unit tests for PromptStore."""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.content.models import PromptVersion
from app.modules.content.prompt_store import PromptStore, _prompt_cache


def _make_session():
    s = MagicMock()
    s.flush = AsyncMock()
    s.add = MagicMock()
    return s


def _make_prompt_version(**kwargs):
    defaults = dict(
        prompt_key="test_key",
        version=1,
        system_text="You are a helpful assistant.",
        user_template="Write about {{business_name}} in {{city}}.",
        recommended_model="claude-sonnet-4-6",
        max_tokens=1000,
        temperature=Decimal("0.0"),
    )
    defaults.update(kwargs)
    return PromptVersion(**defaults)


class TestPromptStore:
    def setup_method(self):
        _prompt_cache.clear()

    def teardown_method(self):
        _prompt_cache.clear()

    @pytest.mark.asyncio
    async def test_get_active_prompt_success(self):
        session = _make_session()
        pv = _make_prompt_version()

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = pv
        session.execute = AsyncMock(return_value=execute_result)

        store = PromptStore(session)
        result = await store.get_active_prompt("test_key")
        assert result is pv

    @pytest.mark.asyncio
    async def test_get_active_prompt_not_found(self):
        from app.core.exceptions import NotFoundError
        session = _make_session()
        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=execute_result)

        store = PromptStore(session)
        with pytest.raises(NotFoundError):
            await store.get_active_prompt("missing_key")

    @pytest.mark.asyncio
    async def test_caches_result(self):
        session = _make_session()
        pv = _make_prompt_version()

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = pv
        session.execute = AsyncMock(return_value=execute_result)

        store = PromptStore(session)
        result1 = await store.get_active_prompt("test_key")
        result2 = await store.get_active_prompt("test_key")

        assert result1 is result2
        assert session.execute.call_count == 1  # Only one DB hit

    @pytest.mark.asyncio
    async def test_invalidate_specific_key(self):
        session = _make_session()
        pv = _make_prompt_version()

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = pv
        session.execute = AsyncMock(return_value=execute_result)

        store = PromptStore(session)
        await store.get_active_prompt("test_key")
        assert len(_prompt_cache) == 1

        await store.invalidate("test_key")
        assert len(_prompt_cache) == 0

    @pytest.mark.asyncio
    async def test_invalidate_all(self):
        session = _make_session()
        pv = _make_prompt_version()

        execute_result = MagicMock()
        execute_result.scalar_one_or_none.return_value = pv
        session.execute = AsyncMock(return_value=execute_result)

        store = PromptStore(session)
        await store.get_active_prompt("key1")
        # Manually insert second entry
        _prompt_cache["key2:en-IN:control"] = (pv, time.time())

        await store.invalidate()
        assert len(_prompt_cache) == 0

    @pytest.mark.asyncio
    async def test_render_prompt_substitution(self):
        session = _make_session()
        pv = _make_prompt_version(
            system_text="System for {{business_name}}",
            user_template="Tell me about {{business_name}} in {{city}}",
        )

        store = PromptStore(session)
        system, user = await store.render_prompt(pv, {"business_name": "Sunrise Bakery", "city": "Bangalore"})
        assert "Sunrise Bakery" in system
        assert "Sunrise Bakery" in user
        assert "Bangalore" in user
        assert "{{" not in user

    @pytest.mark.asyncio
    async def test_render_prompt_no_substitutions(self):
        session = _make_session()
        pv = _make_prompt_version(
            system_text="Static system",
            user_template="Static user",
        )
        store = PromptStore(session)
        system, user = await store.render_prompt(pv, {})
        assert system == "Static system"
        assert user == "Static user"
