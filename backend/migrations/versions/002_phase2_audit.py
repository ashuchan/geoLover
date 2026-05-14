"""Phase 2: Audit & Citation Detection schema

Revision ID: 002_phase2_audit
Revises: 001_phase1_initial
Create Date: 2026-05-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_phase2_audit"
down_revision: Union[str, None] = "001_phase1_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enums ──────────────────────────────────────────────────────────────────
    op.execute("CREATE TYPE engine_health AS ENUM ('healthy', 'degraded', 'unhealthy', 'paused')")
    op.execute("CREATE TYPE audit_status AS ENUM ('pending', 'running', 'partial', 'completed', 'failed')")
    op.execute("CREATE TYPE audit_trigger AS ENUM ('free_audit', 'initial', 'weekly', 'manual', 'redetection', 'api')")
    op.execute("CREATE TYPE query_execution_status AS ENUM ('pending', 'in_flight', 'succeeded', 'failed', 'skipped')")
    op.execute(
        "CREATE TYPE citation_match_type AS ENUM "
        "('exact_name', 'alias', 'phone', 'website', 'address', 'fuzzy_name', 'composite')"
    )
    op.execute("CREATE TYPE citation_polarity AS ENUM ('positive', 'neutral', 'negative')")

    # ── query_template_sets (global reference data — no RLS) ────────────────────
    op.execute("""
        CREATE TABLE query_template_sets (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug VARCHAR(80) NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            locale VARCHAR(10) NOT NULL DEFAULT 'en-IN',
            is_default BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX ix_query_template_sets_slug ON query_template_sets (slug)")

    # ── query_templates (global reference data — no RLS) ───────────────────────
    op.execute("""
        CREATE TABLE query_templates (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            template_set_id UUID NOT NULL REFERENCES query_template_sets(id) ON DELETE CASCADE,
            template_text TEXT NOT NULL,
            required_variables TEXT[] NOT NULL DEFAULT '{}',
            priority INTEGER NOT NULL DEFAULT 100,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_query_templates_set ON query_templates (template_set_id)")

    # ── engine_descriptors (global reference data — no RLS) ────────────────────
    op.execute("""
        CREATE TABLE engine_descriptors (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            slug VARCHAR(80) NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            provider VARCHAR(80) NOT NULL,
            adapter_class TEXT NOT NULL,
            supported_locales TEXT[] NOT NULL DEFAULT '{"en-IN"}',
            health engine_health NOT NULL DEFAULT 'healthy',
            cost_per_query_usd NUMERIC(10,6) NOT NULL DEFAULT 0.0,
            config_json JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX ix_engine_descriptors_slug ON engine_descriptors (slug)")

    # ── audit_runs (RLS by tenant_id) ──────────────────────────────────────────
    op.execute("""
        CREATE TABLE audit_runs (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL REFERENCES tenants(id),
            business_id UUID NOT NULL REFERENCES businesses(id),
            trigger audit_trigger NOT NULL,
            status audit_status NOT NULL DEFAULT 'pending',
            ai_visibility_score REAL,
            completeness_pct REAL,
            queries_total INTEGER NOT NULL DEFAULT 0,
            queries_successful INTEGER NOT NULL DEFAULT 0,
            queries_cited INTEGER NOT NULL DEFAULT 0,
            queries_negative INTEGER NOT NULL DEFAULT 0,
            algorithm_version VARCHAR(20) NOT NULL DEFAULT 'v1',
            workflow_run_id TEXT,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_audit_runs_business ON audit_runs (business_id)")
    op.execute("CREATE INDEX ix_audit_runs_tenant ON audit_runs (tenant_id)")
    op.execute("CREATE INDEX ix_audit_runs_tenant_status ON audit_runs (tenant_id, status)")

    # RLS on audit_runs
    op.execute("ALTER TABLE audit_runs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY audit_runs_tenant_isolation ON audit_runs
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
    """)

    # ── query_executions (RLS by tenant_id) ────────────────────────────────────
    op.execute("""
        CREATE TABLE query_executions (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            audit_run_id UUID NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
            tenant_id UUID NOT NULL,
            engine_descriptor_id UUID NOT NULL REFERENCES engine_descriptors(id),
            query_template_id UUID,
            query_text TEXT NOT NULL,
            status query_execution_status NOT NULL DEFAULT 'pending',
            response_text TEXT,
            error_message TEXT,
            latency_ms INTEGER,
            cost_usd NUMERIC(10,6),
            executed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_query_executions_run ON query_executions (audit_run_id)")
    op.execute("CREATE INDEX ix_query_executions_tenant ON query_executions (tenant_id)")

    op.execute("ALTER TABLE query_executions ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY query_executions_tenant_isolation ON query_executions
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
    """)

    # ── citations (RLS by tenant_id) ───────────────────────────────────────────
    op.execute("""
        CREATE TABLE citations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            query_execution_id UUID NOT NULL REFERENCES query_executions(id) ON DELETE CASCADE,
            tenant_id UUID NOT NULL,
            business_id UUID NOT NULL REFERENCES businesses(id),
            cited BOOLEAN NOT NULL,
            confidence REAL NOT NULL,
            match_type citation_match_type,
            polarity citation_polarity NOT NULL DEFAULT 'neutral',
            snippet TEXT NOT NULL DEFAULT '',
            snippet_start_pos INTEGER NOT NULL DEFAULT 0,
            corroborating_signals TEXT[] NOT NULL DEFAULT '{}',
            competitors_mentioned TEXT[] NOT NULL DEFAULT '{}',
            algorithm_version VARCHAR(20) NOT NULL DEFAULT 'v1',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_citations_execution ON citations (query_execution_id)")
    op.execute("CREATE INDEX ix_citations_tenant ON citations (tenant_id)")
    op.execute("CREATE INDEX ix_citations_business ON citations (business_id)")

    op.execute("ALTER TABLE citations ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY citations_tenant_isolation ON citations
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
    """)

    # ── competitor_observations (RLS by tenant_id) ─────────────────────────────
    op.execute("""
        CREATE TABLE competitor_observations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            audit_run_id UUID NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
            tenant_id UUID NOT NULL,
            business_id UUID NOT NULL REFERENCES businesses(id),
            competitor_name TEXT NOT NULL,
            competitor_name_normalized TEXT NOT NULL,
            mention_count INTEGER NOT NULL DEFAULT 1,
            first_seen_in_execution_id UUID,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_competitor_obs_run ON competitor_observations (audit_run_id)")
    op.execute("CREATE INDEX ix_competitor_obs_tenant ON competitor_observations (tenant_id)")
    op.execute("CREATE INDEX ix_competitor_obs_business ON competitor_observations (business_id)")

    op.execute("ALTER TABLE competitor_observations ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY competitor_obs_tenant_isolation ON competitor_observations
        USING (tenant_id = current_setting('app.current_tenant')::uuid)
        WITH CHECK (tenant_id = current_setting('app.current_tenant')::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS competitor_observations CASCADE")
    op.execute("DROP TABLE IF EXISTS citations CASCADE")
    op.execute("DROP TABLE IF EXISTS query_executions CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_runs CASCADE")
    op.execute("DROP TABLE IF EXISTS engine_descriptors CASCADE")
    op.execute("DROP TABLE IF EXISTS query_templates CASCADE")
    op.execute("DROP TABLE IF EXISTS query_template_sets CASCADE")

    op.execute("DROP TYPE IF EXISTS citation_polarity")
    op.execute("DROP TYPE IF EXISTS citation_match_type")
    op.execute("DROP TYPE IF EXISTS query_execution_status")
    op.execute("DROP TYPE IF EXISTS audit_trigger")
    op.execute("DROP TYPE IF EXISTS audit_status")
    op.execute("DROP TYPE IF EXISTS engine_health")
