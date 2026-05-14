"""Unit tests for Quick Wins generation and validation."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.modules.reporting.models import EffortEstimate, QuickWinActionType
from app.modules.reporting.quick_wins import (
    AuditContext,
    DeterministicQuickWinsGenerator,
    QuickWin,
    QuickWinsGenerator,
    QuickWinsValidator,
    _build_llm_prompt,
)


def _make_ctx(**kwargs) -> AuditContext:
    defaults = dict(
        business_name="Test Bakery",
        category="bakery",
        locality="Koramangala",
        city="Bangalore",
        keywords=["fresh bread", "cakes"],
        score=45.0,
        confidence_band="medium",
        completeness_pct=0.85,
        engines_covered=["openai-chat-v1", "perplexity-online-v1"],
        lost_queries=["best bakery in Koramangala", "fresh cake shop Bangalore"],
        winning_queries=["artisan bread near me"],
        competitors=["Bread & Beyond", "Sugar Rush"],
        lost_query_competitors={"best bakery in Koramangala": "Bread & Beyond"},
        has_phone=True,
        has_website=True,
        has_description=False,
        aliases_count=0,
    )
    defaults.update(kwargs)
    return AuditContext(**defaults)


def _make_valid_win(action_type: str = "add_alias") -> dict:
    return {
        "title": "Test Quick Win Title",
        "description": "A specific actionable recommendation for this business.",
        "action_type": action_type,
        "effort_estimate": "quick",
        "confidence": 0.8,
        "target_query": None,
        "target_engine": None,
    }


class TestQuickWinsValidator:
    def test_valid_three_wins(self):
        validator = QuickWinsValidator()
        wins = [_make_valid_win("add_alias")] * 3
        result = validator.validate(wins)
        assert len(result) == 3
        for win in result:
            assert "id" in win
            assert win["action_type"] == "add_alias"

    def test_not_a_list(self):
        validator = QuickWinsValidator()
        with pytest.raises(ValueError, match="JSON array"):
            validator.validate({"key": "value"})

    def test_wrong_count(self):
        validator = QuickWinsValidator()
        with pytest.raises(ValueError, match="exactly 3"):
            validator.validate([_make_valid_win()] * 2)

    def test_invalid_action_type(self):
        validator = QuickWinsValidator()
        wins = [_make_valid_win("buy_backlinks")] * 3
        with pytest.raises(ValueError, match="not in active vocabulary"):
            validator.validate(wins)

    def test_inactive_action_type_generate_faq(self):
        # generate_faq_content is inactive at Phase 3 launch
        validator = QuickWinsValidator()
        wins = [_make_valid_win("generate_faq_content")] * 3
        with pytest.raises(ValueError, match="not in active vocabulary"):
            validator.validate(wins)

    def test_inactive_action_type_seed_directory(self):
        validator = QuickWinsValidator()
        wins = [_make_valid_win("seed_directory")] * 3
        with pytest.raises(ValueError, match="not in active vocabulary"):
            validator.validate(wins)

    def test_title_too_long(self):
        validator = QuickWinsValidator()
        win = _make_valid_win()
        win["title"] = "x" * 81
        with pytest.raises(ValueError, match="title must be 1-80"):
            validator.validate([win] * 3)

    def test_title_empty(self):
        validator = QuickWinsValidator()
        win = _make_valid_win()
        win["title"] = ""
        with pytest.raises(ValueError, match="title must be 1-80"):
            validator.validate([win] * 3)

    def test_description_too_long(self):
        validator = QuickWinsValidator()
        win = _make_valid_win()
        win["description"] = "x" * 301
        with pytest.raises(ValueError, match="description must be 1-300"):
            validator.validate([win] * 3)

    def test_description_empty(self):
        validator = QuickWinsValidator()
        win = _make_valid_win()
        win["description"] = ""
        with pytest.raises(ValueError, match="description must be 1-300"):
            validator.validate([win] * 3)

    def test_forbidden_phrase_backlinks(self):
        validator = QuickWinsValidator()
        win = _make_valid_win()
        win["description"] = "You should buy backlinks to improve ranking"
        with pytest.raises(ValueError, match="forbidden phrase"):
            validator.validate([win] * 3)

    def test_forbidden_phrase_url(self):
        validator = QuickWinsValidator()
        win = _make_valid_win()
        win["description"] = "Visit https://spamsite.com for help"
        with pytest.raises(ValueError, match="forbidden phrase"):
            validator.validate([win] * 3)

    def test_invalid_target_query(self):
        validator = QuickWinsValidator(lost_queries=["query A"])
        win = _make_valid_win()
        win["target_query"] = "unknown query"
        with pytest.raises(ValueError, match="target_query"):
            validator.validate([win] * 3)

    def test_valid_target_query(self):
        validator = QuickWinsValidator(lost_queries=["query A"])
        win = _make_valid_win()
        win["target_query"] = "query A"
        result = validator.validate([win] * 3)
        assert result[0]["target_query"] == "query A"

    def test_invalid_target_engine(self):
        validator = QuickWinsValidator(valid_engine_keys=["engine-a"])
        win = _make_valid_win()
        win["target_engine"] = "unknown-engine"
        with pytest.raises(ValueError, match="target_engine"):
            validator.validate([win] * 3)

    def test_invalid_effort_estimate(self):
        validator = QuickWinsValidator()
        win = _make_valid_win()
        win["effort_estimate"] = "instant"
        with pytest.raises(ValueError, match="effort_estimate"):
            validator.validate([win] * 3)

    def test_confidence_out_of_range(self):
        validator = QuickWinsValidator()
        win = _make_valid_win()
        win["confidence"] = 1.5
        with pytest.raises(ValueError, match="confidence must be 0-1"):
            validator.validate([win] * 3)

    def test_confidence_negative(self):
        validator = QuickWinsValidator()
        win = _make_valid_win()
        win["confidence"] = -0.1
        with pytest.raises(ValueError, match="confidence must be 0-1"):
            validator.validate([win] * 3)

    def test_not_a_dict_item(self):
        validator = QuickWinsValidator()
        with pytest.raises(ValueError, match="not an object"):
            validator.validate(["string", "string", "string"])

    def test_all_active_action_types_accepted(self):
        validator = QuickWinsValidator()
        active_types = ["add_alias", "add_keyword", "update_gbp_description",
                        "add_location_detail", "clarify_service_offering"]
        for action_type in active_types:
            wins = [_make_valid_win(action_type)] * 3
            result = validator.validate(wins)
            assert len(result) == 3


class TestDeterministicQuickWinsGenerator:
    def test_produces_three_wins(self):
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx()
        wins = gen.generate(ctx)
        assert len(wins) == 3

    def test_all_wins_have_required_fields(self):
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx()
        wins = gen.generate(ctx)
        for win in wins:
            assert "id" in win
            assert "title" in win
            assert "description" in win
            assert "action_type" in win
            assert "effort_estimate" in win
            assert "confidence" in win

    def test_produces_add_alias_when_no_aliases(self):
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx(aliases_count=0, lost_queries=["best bakery Bangalore"])
        wins = gen.generate(ctx)
        action_types = [w["action_type"] for w in wins]
        assert "add_alias" in action_types

    def test_produces_add_keyword_when_has_aliases(self):
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx(aliases_count=2, lost_queries=["best bakery Bangalore"])
        wins = gen.generate(ctx)
        action_types = [w["action_type"] for w in wins]
        assert "add_keyword" in action_types

    def test_produces_add_location_when_no_queries(self):
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx(aliases_count=0, lost_queries=[], keywords=[])
        wins = gen.generate(ctx)
        action_types = [w["action_type"] for w in wins]
        assert "add_location_detail" in action_types

    def test_gbp_win_when_no_description(self):
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx(has_description=False)
        wins = gen.generate(ctx)
        action_types = [w["action_type"] for w in wins]
        assert "update_gbp_description" in action_types

    def test_clarify_service_when_has_description(self):
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx(has_description=True)
        wins = gen.generate(ctx)
        action_types = [w["action_type"] for w in wins]
        assert "clarify_service_offering" in action_types

    def test_no_empty_titles(self):
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx()
        wins = gen.generate(ctx)
        for win in wins:
            assert win["title"].strip() != ""

    def test_no_empty_descriptions(self):
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx()
        wins = gen.generate(ctx)
        for win in wins:
            assert win["description"].strip() != ""

    def test_all_action_types_in_active_vocab(self):
        from app.modules.reporting.quick_wins import _ACTIVE_ACTION_TYPES
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx()
        wins = gen.generate(ctx)
        for win in wins:
            assert QuickWinActionType(win["action_type"]) in _ACTIVE_ACTION_TYPES

    def test_empty_lost_queries(self):
        gen = DeterministicQuickWinsGenerator()
        ctx = _make_ctx(lost_queries=[], winning_queries=[])
        wins = gen.generate(ctx)
        assert len(wins) == 3

    def test_many_lost_queries(self):
        gen = DeterministicQuickWinsGenerator()
        lost = [f"query {i}" for i in range(20)]
        ctx = _make_ctx(lost_queries=lost)
        wins = gen.generate(ctx)
        assert len(wins) == 3


class TestBuildLlmPrompt:
    def test_system_contains_schema(self):
        ctx = _make_ctx()
        system, user = _build_llm_prompt(ctx)
        assert "JSON array" in system
        assert "action_type" in system

    def test_user_contains_business_info(self):
        ctx = _make_ctx(business_name="My Bakery", city="Pune")
        _, user = _build_llm_prompt(ctx)
        assert "My Bakery" in user
        assert "Pune" in user

    def test_user_contains_lost_queries(self):
        ctx = _make_ctx(lost_queries=["best bakery", "cake shop"])
        _, user = _build_llm_prompt(ctx)
        assert "best bakery" in user

    def test_user_contains_score(self):
        ctx = _make_ctx(score=42.0)
        _, user = _build_llm_prompt(ctx)
        assert "42.0" in user


class TestQuickWinsGenerator:
    @pytest.mark.asyncio
    async def test_no_gateway_uses_fallback(self):
        gen = QuickWinsGenerator(gateway=None)
        ctx = _make_ctx()
        wins = await gen.generate(ctx)
        assert len(wins) == 3

    @pytest.mark.asyncio
    async def test_gateway_success_returns_llm_wins(self):
        llm_wins = [_make_valid_win("add_alias")] * 3
        response_text = json.dumps(llm_wins)

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.response_text = response_text

        gateway = MagicMock()
        gateway.complete = AsyncMock(return_value=mock_response)

        gen = QuickWinsGenerator(gateway=gateway)
        ctx = _make_ctx()
        wins = await gen.generate(ctx)
        assert len(wins) == 3

    @pytest.mark.asyncio
    async def test_gateway_empty_response_falls_back(self):
        mock_response = MagicMock()
        mock_response.success = False
        mock_response.response_text = ""

        gateway = MagicMock()
        gateway.complete = AsyncMock(return_value=mock_response)

        gen = QuickWinsGenerator(gateway=gateway)
        ctx = _make_ctx()
        wins = await gen.generate(ctx)
        assert len(wins) == 3

    @pytest.mark.asyncio
    async def test_gateway_exception_falls_back(self):
        gateway = MagicMock()
        gateway.complete = AsyncMock(side_effect=RuntimeError("LLM down"))

        gen = QuickWinsGenerator(gateway=gateway)
        ctx = _make_ctx()
        wins = await gen.generate(ctx)
        assert len(wins) == 3

    @pytest.mark.asyncio
    async def test_gateway_invalid_json_falls_back(self):
        mock_response = MagicMock()
        mock_response.success = True
        mock_response.response_text = "not json at all"

        gateway = MagicMock()
        gateway.complete = AsyncMock(return_value=mock_response)

        gen = QuickWinsGenerator(gateway=gateway)
        ctx = _make_ctx()
        wins = await gen.generate(ctx)
        assert len(wins) == 3

    @pytest.mark.asyncio
    async def test_gateway_response_with_markdown_fence(self):
        llm_wins = [_make_valid_win("add_alias")] * 3
        response_text = f"```json\n{json.dumps(llm_wins)}\n```"

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.response_text = response_text

        gateway = MagicMock()
        gateway.complete = AsyncMock(return_value=mock_response)

        gen = QuickWinsGenerator(gateway=gateway)
        ctx = _make_ctx()
        wins = await gen.generate(ctx)
        assert len(wins) == 3

    @pytest.mark.asyncio
    async def test_gateway_invalid_vocab_retries_then_falls_back(self):
        # Return invalid action_type on first two attempts, causing fallback
        llm_wins = [_make_valid_win("buy_backlinks")] * 3
        response_text = json.dumps(llm_wins)

        mock_response = MagicMock()
        mock_response.success = True
        mock_response.response_text = response_text

        gateway = MagicMock()
        gateway.complete = AsyncMock(return_value=mock_response)

        gen = QuickWinsGenerator(gateway=gateway)
        ctx = _make_ctx()
        wins = await gen.generate(ctx)
        assert len(wins) == 3
        # Should have tried 2 times (both fail validation) then fallen back
        assert gateway.complete.call_count == 2


class TestQuickWinDataclass:
    def test_to_dict(self):
        win = QuickWin(
            id=uuid.uuid4(),
            title="Add alias",
            description="Add variant names",
            action_type=QuickWinActionType.add_alias,
            effort_estimate=EffortEstimate.quick,
            confidence=0.8,
            target_query="best bakery",
            target_engine="openai-chat-v1",
        )
        d = win.to_dict()
        assert d["title"] == "Add alias"
        assert d["action_type"] == "add_alias"
        assert d["effort_estimate"] == "quick"
        assert d["confidence"] == 0.8
        assert d["target_query"] == "best bakery"

    def test_to_dict_no_target(self):
        win = QuickWin(
            id=uuid.uuid4(),
            title="Test",
            description="Desc",
            action_type=QuickWinActionType.add_keyword,
            effort_estimate=EffortEstimate.medium,
            confidence=0.7,
        )
        d = win.to_dict()
        assert d["target_query"] is None
        assert d["target_engine"] is None
