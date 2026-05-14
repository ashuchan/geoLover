"""Phase 3: Reporting & Free Audit Experience schema

Revision ID: 003_phase3_reporting
Revises: 002_phase2_audit
Create Date: 2026-05-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_phase3_reporting"
down_revision: Union[str, None] = "002_phase2_audit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enums ──────────────────────────────────────────────────────────────────
    op.execute("CREATE TYPE report_status AS ENUM ('generating', 'ready', 'failed')")

    # ── reports ────────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE reports (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            business_id UUID NOT NULL,
            audit_run_id UUID NOT NULL REFERENCES audit_runs(id),
            version INTEGER NOT NULL DEFAULT 1,
            status report_status NOT NULL DEFAULT 'generating',
            score REAL,
            confidence_band VARCHAR(32),
            completeness_pct REAL,
            pdf_gcs_uri TEXT,
            pdf_byte_size INTEGER,
            pdf_checksum VARCHAR(64),
            web_view_token VARCHAR(64) NOT NULL UNIQUE,
            quick_wins JSONB,
            template_version VARCHAR(32) NOT NULL DEFAULT 'v1',
            generated_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (audit_run_id, version)
        )
    """)
    op.execute("CREATE INDEX ix_reports_business_created ON reports(business_id, created_at DESC)")
    op.execute("CREATE INDEX ix_reports_audit_run ON reports(audit_run_id)")
    op.execute("CREATE INDEX ix_reports_generating ON reports(status) WHERE status = 'generating'")

    # RLS on reports
    op.execute("ALTER TABLE reports ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY reports_tenant_isolation ON reports
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
    """)

    # ── share_links ────────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE share_links (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            business_id UUID NOT NULL,
            report_id UUID NOT NULL REFERENCES reports(id),
            token VARCHAR(48) NOT NULL UNIQUE,
            created_by_user_id UUID,
            expires_at TIMESTAMPTZ NOT NULL,
            revoked_at TIMESTAMPTZ,
            view_count INTEGER NOT NULL DEFAULT 0,
            last_viewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX ix_share_links_token ON share_links(token)")
    op.execute("CREATE INDEX ix_share_links_report ON share_links(report_id)")

    # RLS on share_links
    op.execute("ALTER TABLE share_links ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY share_links_tenant_isolation ON share_links
            USING (tenant_id = current_setting('app.current_tenant')::uuid)
    """)

    # ── Extend free_audit_tokens with audit_run_id ─────────────────────────────
    op.execute("""
        ALTER TABLE free_audit_tokens
            ADD COLUMN IF NOT EXISTS audit_run_id UUID REFERENCES audit_runs(id)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_free_audit_tokens_email
            ON free_audit_tokens(submitter_email_normalized)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE free_audit_tokens DROP COLUMN IF EXISTS audit_run_id")
    op.execute("DROP TABLE IF EXISTS share_links CASCADE")
    op.execute("DROP TABLE IF EXISTS reports CASCADE")
    op.execute("DROP TYPE IF EXISTS report_status")
