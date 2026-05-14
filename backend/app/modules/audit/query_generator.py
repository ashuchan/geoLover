"""QueryGenerator — variable substitution + deduplication for query templates.

Replaces {variable} placeholders in templates with values from a context dict.
Skips templates where required variables are missing.
Deduplicates generated queries (case-insensitive, whitespace-normalised).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class GeneratedQuery:
    """A single query ready for execution."""

    query_text: str
    template_id: Optional[str]  # source template ID (UUID as str) or None
    priority: int


def _normalize_for_dedup(text: str) -> str:
    """Lowercase + collapse whitespace for deduplication."""
    return re.sub(r"\s+", " ", text.lower()).strip()


class QueryGenerator:
    """Generates concrete query strings from templates + variable context."""

    def generate(
        self,
        templates: list[dict],
        context: dict[str, str],
        *,
        max_queries: int = 1000,
    ) -> list[GeneratedQuery]:
        """Generate queries from templates.

        Args:
            templates: list of dicts with keys:
                - template_text: str with {variable} placeholders
                - required_variables: list[str] of required variable names
                - id: optional str template ID
                - priority: int (default 100)
            context: mapping of variable name → value
            max_queries: cap on returned queries

        Returns:
            Deduplicated list of GeneratedQuery sorted by priority asc.
        """
        seen: set[str] = set()
        results: list[GeneratedQuery] = []

        for tmpl in templates:
            template_text: str = tmpl.get("template_text", "")
            required: list[str] = tmpl.get("required_variables", [])
            template_id: Optional[str] = tmpl.get("id")
            priority: int = tmpl.get("priority", 100)

            # Skip if any required variable is missing or empty
            if any(context.get(v, "").strip() == "" for v in required):
                continue

            # Substitute variables
            try:
                query_text = self._substitute(template_text, context)
            except KeyError:
                # Template references a variable not in context; skip
                continue

            # Normalise and deduplicate
            norm = _normalize_for_dedup(query_text)
            if norm in seen:
                continue
            seen.add(norm)

            results.append(
                GeneratedQuery(
                    query_text=query_text,
                    template_id=template_id,
                    priority=priority,
                )
            )

            if len(results) >= max_queries:
                break

        results.sort(key=lambda q: q.priority)
        return results

    def _substitute(self, template_text: str, context: dict[str, str]) -> str:
        """Replace {variable} placeholders.  Raises KeyError if variable missing."""
        def replacer(m: re.Match) -> str:
            key = m.group(1)
            if key not in context:
                raise KeyError(key)
            return context[key]

        return re.sub(r"\{(\w+)\}", replacer, template_text)
