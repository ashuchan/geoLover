"""Unit tests for QueryGenerator."""

from __future__ import annotations

import pytest

from app.modules.audit.query_generator import GeneratedQuery, QueryGenerator


def _t(text: str, required: list[str], priority: int = 100, tid: str | None = "t1") -> dict:
    return {"template_text": text, "required_variables": required, "priority": priority, "id": tid}


class TestQueryGenerator:
    def setup_method(self):
        self.gen = QueryGenerator()

    def test_basic_substitution(self):
        templates = [_t("Best {category} in {city}", ["category", "city"])]
        context = {"category": "dental clinic", "city": "Bengaluru"}
        results = self.gen.generate(templates, context)
        assert len(results) == 1
        assert results[0].query_text == "Best dental clinic in Bengaluru"

    def test_skips_missing_required_variable(self):
        templates = [_t("Best {category} in {city}", ["category", "city"])]
        context = {"category": "dental clinic"}  # city missing
        results = self.gen.generate(templates, context)
        assert len(results) == 0

    def test_skips_empty_required_variable(self):
        templates = [_t("Best {category} in {city}", ["category", "city"])]
        context = {"category": "dental clinic", "city": ""}
        results = self.gen.generate(templates, context)
        assert len(results) == 0

    def test_deduplication(self):
        templates = [
            _t("Best {category} in {city}", ["category", "city"], tid="t1"),
            _t("BEST {category} IN {city}", ["category", "city"], tid="t2"),  # same after normalise
        ]
        context = {"category": "dental", "city": "Bengaluru"}
        results = self.gen.generate(templates, context)
        assert len(results) == 1

    def test_deduplication_whitespace(self):
        templates = [
            _t("dental in  bengaluru", [], tid="t1"),
            _t("dental in bengaluru", [], tid="t2"),  # same after whitespace normalise
        ]
        results = self.gen.generate(templates, {})
        assert len(results) == 1

    def test_sorted_by_priority(self):
        templates = [
            _t("query three", [], priority=300, tid="t3"),
            _t("query one", [], priority=100, tid="t1"),
            _t("query two", [], priority=200, tid="t2"),
        ]
        results = self.gen.generate(templates, {})
        assert results[0].query_text == "query one"
        assert results[1].query_text == "query two"
        assert results[2].query_text == "query three"

    def test_max_queries_cap(self):
        templates = [_t(f"query {i}", [], priority=i, tid=f"t{i}") for i in range(20)]
        results = self.gen.generate(templates, {}, max_queries=5)
        assert len(results) == 5

    def test_template_id_preserved(self):
        templates = [_t("test query", [], tid="my-template-id")]
        results = self.gen.generate(templates, {})
        assert results[0].template_id == "my-template-id"

    def test_no_templates(self):
        results = self.gen.generate([], {})
        assert results == []

    def test_template_without_variables(self):
        templates = [_t("What is AI Overviews?", [], tid="t1")]
        results = self.gen.generate(templates, {})
        assert len(results) == 1
        assert results[0].query_text == "What is AI Overviews?"

    def test_multiple_variables(self):
        templates = [_t("{service} near {locality} {city}", ["service", "locality", "city"])]
        context = {"service": "CA firm", "locality": "Koramangala", "city": "Bengaluru"}
        results = self.gen.generate(templates, context)
        assert results[0].query_text == "CA firm near Koramangala Bengaluru"

    def test_extra_context_ignored(self):
        templates = [_t("Best {category}", ["category"])]
        context = {"category": "dental", "extra": "ignored"}
        results = self.gen.generate(templates, context)
        assert len(results) == 1

    def test_unknown_variable_in_template_skipped(self):
        """Template references {unknown} not in context → skip."""
        templates = [_t("Best {unknown}", ["unknown"])]
        context = {}
        results = self.gen.generate(templates, context)
        assert len(results) == 0
