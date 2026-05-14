"""Quick Wins generation for audit reports.

Two modes:
1. LLM-generated (preferred) — calls LLMGateway with a structured prompt.
2. Deterministic fallback — rule-based generator, always produces 3 wins.

The closed vocabulary of action_types is enforced by the validator.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from app.modules.engines.protocol import ProbeBudget, QueryIntent
from app.modules.reporting.models import EffortEstimate, QuickWinActionType

_log = logging.getLogger(__name__)

TEMPLATE_VERSION = "v1"

# Active action types at Phase 3 launch (Phase 4/5 activate more)
_ACTIVE_ACTION_TYPES = frozenset({
    QuickWinActionType.add_alias,
    QuickWinActionType.add_keyword,
    QuickWinActionType.update_gbp_description,
    QuickWinActionType.add_location_detail,
    QuickWinActionType.clarify_service_offering,
})

_FORBIDDEN_PHRASES = frozenset({
    "buy backlinks",
    "pay for reviews",
    "http://",
    "https://",
    "buy links",
    "paid reviews",
})

QUICK_WIN_SCHEMA = {
    "type": "array",
    "minItems": 3,
    "maxItems": 3,
    "items": {
        "type": "object",
        "required": ["title", "description", "action_type", "effort_estimate", "confidence"],
        "properties": {
            "title": {"type": "string", "maxLength": 80},
            "description": {"type": "string", "maxLength": 300},
            "action_type": {"type": "string", "enum": [t.value for t in _ACTIVE_ACTION_TYPES]},
            "target_query": {"type": "string"},
            "target_engine": {"type": "string"},
            "effort_estimate": {"type": "string", "enum": [e.value for e in EffortEstimate]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    },
}


@dataclass
class QuickWin:
    id: uuid.UUID
    title: str
    description: str
    action_type: QuickWinActionType
    effort_estimate: EffortEstimate
    confidence: float
    target_query: Optional[str] = None
    target_engine: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "title": self.title,
            "description": self.description,
            "action_type": self.action_type.value,
            "effort_estimate": self.effort_estimate.value,
            "confidence": self.confidence,
            "target_query": self.target_query,
            "target_engine": self.target_engine,
        }


@dataclass
class AuditContext:
    """Context passed to the Quick Wins generator."""

    business_name: str
    category: str
    locality: str
    city: str
    keywords: list[str]
    score: float
    confidence_band: str
    completeness_pct: float
    engines_covered: list[str]
    lost_queries: list[str]
    winning_queries: list[str]
    competitors: list[str]
    lost_query_competitors: dict[str, str]  # query → competitor cited
    has_phone: bool = False
    has_website: bool = False
    has_description: bool = False
    aliases_count: int = 0


class QuickWinsValidator:
    """Validates LLM-generated Quick Wins against constraints."""

    def __init__(
        self,
        *,
        lost_queries: list[str] | None = None,
        valid_engine_keys: list[str] | None = None,
    ) -> None:
        self._lost_queries = set(lost_queries or [])
        self._valid_engines = set(valid_engine_keys or [])

    def validate(self, raw: Any) -> list[dict]:
        """Validate and return list of valid Quick Win dicts, or raise ValueError."""
        if not isinstance(raw, list):
            raise ValueError("Quick Wins must be a JSON array")
        if len(raw) != 3:
            raise ValueError(f"Expected exactly 3 Quick Wins, got {len(raw)}")

        validated = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ValueError(f"Quick Win {i} is not an object")
            validated.append(self._validate_one(i, item))
        return validated

    def _validate_one(self, idx: int, item: dict) -> dict:
        # action_type must be in active vocabulary
        action_type = item.get("action_type", "")
        active_values = {t.value for t in _ACTIVE_ACTION_TYPES}
        if action_type not in active_values:
            raise ValueError(
                f"Quick Win {idx}: action_type '{action_type}' not in active vocabulary {active_values}"
            )

        # title length
        title = item.get("title", "")
        if not title or len(title) > 80:
            raise ValueError(f"Quick Win {idx}: title must be 1-80 chars, got '{title}'")

        # description length
        desc = item.get("description", "")
        if not desc or len(desc) > 300:
            raise ValueError(f"Quick Win {idx}: description must be 1-300 chars")

        # forbidden phrases — checked in both title and description
        for field_name, field_val in (("title", title), ("description", desc)):
            field_lower = field_val.lower()
            for phrase in _FORBIDDEN_PHRASES:
                if phrase in field_lower:
                    raise ValueError(
                        f"Quick Win {idx}: {field_name} contains forbidden phrase '{phrase}'"
                    )

        # target_query must be from lost_queries if specified
        target_query = item.get("target_query")
        if target_query and self._lost_queries and target_query not in self._lost_queries:
            raise ValueError(
                f"Quick Win {idx}: target_query '{target_query}' not in lost_queries"
            )

        # target_engine must be valid if specified
        target_engine = item.get("target_engine")
        if target_engine and self._valid_engines and target_engine not in self._valid_engines:
            raise ValueError(
                f"Quick Win {idx}: target_engine '{target_engine}' not in valid engines"
            )

        # effort_estimate
        effort = item.get("effort_estimate", "")
        if effort not in {e.value for e in EffortEstimate}:
            raise ValueError(f"Quick Win {idx}: invalid effort_estimate '{effort}'")

        # confidence
        conf = item.get("confidence", -1)
        if not isinstance(conf, (int, float)) or not (0 <= conf <= 1):
            raise ValueError(f"Quick Win {idx}: confidence must be 0-1 float")

        return {
            "id": str(uuid.uuid4()),
            "title": title[:80],
            "description": desc[:300],
            "action_type": action_type,
            "effort_estimate": effort,
            "confidence": float(conf),
            "target_query": target_query,
            "target_engine": target_engine,
        }


class DeterministicQuickWinsGenerator:
    """Rule-based fallback that always produces exactly 3 Quick Wins."""

    def generate(self, ctx: AuditContext) -> list[dict]:
        wins: list[dict] = []

        # Win 1: alias or keyword based on lost queries
        if ctx.aliases_count == 0 and ctx.lost_queries:
            wins.append({
                "id": str(uuid.uuid4()),
                "title": f"Add alternate name variants for {ctx.business_name}",
                "description": (
                    f"Your business may be referred to differently in AI responses. "
                    f"Adding common name variants improves recognition across lost queries like "
                    f"'{ctx.lost_queries[0][:60]}'."
                ),
                "action_type": QuickWinActionType.add_alias.value,
                "effort_estimate": EffortEstimate.quick.value,
                "confidence": 0.75,
                "target_query": ctx.lost_queries[0] if ctx.lost_queries else None,
                "target_engine": None,
            })
        elif ctx.keywords and ctx.lost_queries:
            wins.append({
                "id": str(uuid.uuid4()),
                "title": f"Add keyword targeting '{ctx.lost_queries[0][:40]}'",
                "description": (
                    f"The query '{ctx.lost_queries[0][:60]}' is not matched by your current keywords. "
                    f"Adding it to your business profile will improve AI citation recall."
                ),
                "action_type": QuickWinActionType.add_keyword.value,
                "effort_estimate": EffortEstimate.quick.value,
                "confidence": 0.72,
                "target_query": ctx.lost_queries[0] if ctx.lost_queries else None,
                "target_engine": None,
            })
        else:
            wins.append({
                "id": str(uuid.uuid4()),
                "title": "Add location detail to your business profile",
                "description": (
                    f"Complete locality and address information for {ctx.business_name} in "
                    f"{ctx.city} helps AI engines recognise your business in local queries."
                ),
                "action_type": QuickWinActionType.add_location_detail.value,
                "effort_estimate": EffortEstimate.quick.value,
                "confidence": 0.65,
                "target_query": None,
                "target_engine": None,
            })

        # Win 2: GBP description
        if not ctx.has_description:
            wins.append({
                "id": str(uuid.uuid4()),
                "title": f"Write a GBP description for {ctx.business_name}",
                "description": (
                    f"A detailed Google Business Profile description for your {ctx.category} "
                    f"business in {ctx.locality or ctx.city} helps AI engines surface you in "
                    f"relevant queries."
                ),
                "action_type": QuickWinActionType.update_gbp_description.value,
                "effort_estimate": EffortEstimate.medium.value,
                "confidence": 0.80,
                "target_query": None,
                "target_engine": None,
            })
        else:
            wins.append({
                "id": str(uuid.uuid4()),
                "title": f"Clarify your service offering in your profile",
                "description": (
                    f"Adding specific service descriptions for {ctx.category} queries in "
                    f"{ctx.city} will help AI engines match your business to more relevant searches."
                ),
                "action_type": QuickWinActionType.clarify_service_offering.value,
                "effort_estimate": EffortEstimate.medium.value,
                "confidence": 0.70,
                "target_query": ctx.lost_queries[1] if len(ctx.lost_queries) > 1 else None,
                "target_engine": None,
            })

        # Win 3: keyword for second lost query or general keyword
        lost_q = ctx.lost_queries[1] if len(ctx.lost_queries) > 1 else None
        wins.append({
            "id": str(uuid.uuid4()),
            "title": f"Expand keyword coverage for {ctx.category} searches",
            "description": (
                f"Adding keywords that match the language AI engines use for {ctx.category} "
                f"businesses in {ctx.city} can increase your citation rate."
                + (f" Start with: '{lost_q[:60]}'." if lost_q else "")
            ),
            "action_type": QuickWinActionType.add_keyword.value,
            "effort_estimate": EffortEstimate.quick.value,
            "confidence": 0.68,
            "target_query": lost_q,
            "target_engine": None,
        })

        return wins[:3]


def _build_llm_prompt(ctx: AuditContext) -> tuple[str, str]:
    """Return (system_prompt, user_prompt) for Quick Wins generation."""
    active_types = sorted(t.value for t in _ACTIVE_ACTION_TYPES)
    schema_str = json.dumps(QUICK_WIN_SCHEMA, indent=2)

    system = (
        "You are a GEO (Generative Engine Optimisation) recommendation engine. "
        "Given an audit of a business's AI citation performance, suggest 3 specific, "
        "actionable improvements. You MUST return a JSON array matching this schema:\n"
        f"{schema_str}\n\n"
        f"Each suggestion's action_type MUST be one of: {active_types}. "
        "Do not invent new action types. Do not suggest things outside this list. "
        "Do not include URLs, backlink advice, or paid review suggestions in descriptions."
    )

    lost_q_lines = "\n".join(
        f"  {i+1}. \"{q}\" — competitor cited: {ctx.lost_query_competitors.get(q, 'unknown')}"
        for i, q in enumerate(ctx.lost_queries[:5])
    )
    win_q_lines = "\n".join(
        f"  {i+1}. \"{q}\"" for i, q in enumerate(ctx.winning_queries[:3])
    )
    comp_str = ", ".join(ctx.competitors[:5]) if ctx.competitors else "none identified"
    kw_str = ", ".join(ctx.keywords[:8]) if ctx.keywords else "none"

    user = (
        f"Business profile:\n"
        f"  Name: {ctx.business_name}\n"
        f"  Category: {ctx.category}\n"
        f"  Locality: {ctx.locality}\n"
        f"  City: {ctx.city}\n"
        f"  Current keywords: {kw_str}\n\n"
        f"Audit summary:\n"
        f"  Score: {ctx.score:.1f}/100, confidence: {ctx.confidence_band}\n"
        f"  Engines covered: {', '.join(ctx.engines_covered)}, completeness: {ctx.completeness_pct*100:.0f}%\n\n"
        f"Top lost queries (business not cited):\n{lost_q_lines or '  (none)'}\n\n"
        f"Top winning queries (business cited):\n{win_q_lines or '  (none)'}\n\n"
        f"Known competitors: {comp_str}\n\n"
        "Suggest 3 Quick Wins as a JSON array. Be specific to this business and these lost queries. "
        "Return ONLY the JSON array, no other text."
    )

    return system, user


class QuickWinsGenerator:
    """Generates Quick Wins using LLM with deterministic fallback."""

    def __init__(self, *, gateway=None) -> None:
        self._gateway = gateway
        self._fallback = DeterministicQuickWinsGenerator()

    async def generate(self, ctx: AuditContext) -> list[dict]:
        """Generate Quick Wins. Returns list of 3 validated QuickWin dicts."""
        validator = QuickWinsValidator(
            lost_queries=ctx.lost_queries,
            valid_engine_keys=ctx.engines_covered,
        )

        if self._gateway is not None:
            for attempt in range(2):
                try:
                    wins = await self._try_llm(ctx, validator, attempt=attempt)
                    if wins:
                        return wins
                except Exception as exc:
                    _log.warning("Quick Wins LLM attempt %d failed: %s", attempt + 1, exc)

        _log.info("Using deterministic Quick Wins fallback")
        raw = self._fallback.generate(ctx)
        return raw

    async def _try_llm(
        self,
        ctx: AuditContext,
        validator: QuickWinsValidator,
        *,
        attempt: int = 0,
    ) -> list[dict] | None:
        system_prompt, user_prompt = _build_llm_prompt(ctx)
        if attempt > 0:
            user_prompt = (
                "Your previous response was invalid. Return ONLY a valid JSON array. "
                + user_prompt
            )

        budget = ProbeBudget(max_cost_usd=0.05, timeout_s=30.0)
        query = QueryIntent(
            query_text=user_prompt,
            locale="en",
        )

        try:
            response = await self._gateway.complete(
                query,
                model="claude-haiku-4-5",
                system_prompt=system_prompt,
                budget=budget,
                timeout_s=30.0,
            )
        except Exception:
            raise

        if not response.success or not response.response_text:
            return None

        # Extract JSON from response (may have markdown code fences)
        text = response.response_text.strip()
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON array found in LLM response")

        raw = json.loads(json_match.group())
        return validator.validate(raw)
