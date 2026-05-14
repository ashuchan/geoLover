"""Phase 4: Content Generation & LLM Gateway

Revision ID: 004_phase4_content
Down revision: 003_phase3_reporting
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "004_phase4_content"
down_revision = "003_phase3_reporting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── prompt_versions ────────────────────────────────────────────────────────
    op.create_table(
        "prompt_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("prompt_key", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("system_text", sa.Text, nullable=False),
        sa.Column("user_template", sa.Text, nullable=False),
        sa.Column("parameters_schema", postgresql.JSONB, nullable=True),
        sa.Column("output_schema", postgresql.JSONB, nullable=True),
        sa.Column("recommended_model", sa.Text, nullable=False),
        sa.Column("temperature", sa.Numeric(3, 2), nullable=False, server_default="0.0"),
        sa.Column("max_tokens", sa.Integer, nullable=False),
        sa.Column("locale", sa.Text, nullable=False, server_default="en-IN"),
        sa.Column("active_flag", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("experiment_cohort", sa.Text, nullable=False, server_default="control"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("prompt_key", "version", name="uq_prompt_versions_key_version"),
    )
    op.create_index("ix_pv_key_locale_cohort", "prompt_versions", ["prompt_key", "locale", "experiment_cohort"])
    op.create_index(
        "ix_pv_active_unique",
        "prompt_versions",
        ["prompt_key", "locale", "experiment_cohort"],
        unique=True,
        postgresql_where=sa.text("active_flag = true AND retired_at IS NULL"),
    )

    # ── enums ──────────────────────────────────────────────────────────────────
    op.execute("CREATE TYPE brief_type AS ENUM ('direct_answer_page','faq_cluster','comparison_page','entity_summary')")
    op.execute("CREATE TYPE brief_state AS ENUM ('draft','in_review','approved','rejected','superseded','published')")
    op.execute("CREATE TYPE approval_flow_type AS ENUM ('agency_only','business_only','agency_then_business')")
    op.execute("CREATE TYPE llm_purpose AS ENUM ('content_brief_gen','audit_quick_wins','pii_redaction','translation','eval','other')")

    # ── content_briefs ─────────────────────────────────────────────────────────
    op.create_table(
        "content_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("source_audit_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("audit_runs.id"), nullable=False),
        sa.Column("source_lost_query_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=True),
        sa.Column("brief_type", sa.Text, nullable=False),
        sa.Column("target_query", sa.Text, nullable=False),
        sa.Column("current_state", sa.Text, nullable=False, server_default="draft"),
        sa.Column("current_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewer_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approval_flow", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_content_briefs_tenant_business", "content_briefs", ["tenant_id", "business_id"])
    op.create_index("ix_content_briefs_state", "content_briefs", ["current_state"])
    op.execute("ALTER TABLE content_briefs ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON content_briefs
        USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
    """)

    # ── content_assets ─────────────────────────────────────────────────────────
    op.create_table(
        "content_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brief_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_briefs.id"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("markdown", sa.Text, nullable=False),
        sa.Column("html", sa.Text, nullable=False),
        sa.Column("schema_jsonld", postgresql.JSONB, nullable=True),
        sa.Column("prompt_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prompt_versions.id"), nullable=False),
        sa.Column("llm_call_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("validation_status", sa.Text, nullable=False, server_default="pending"),
        sa.Column("validation_findings", postgresql.JSONB, nullable=True),
        sa.Column("reviewer_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("brief_id", "version", name="uq_content_assets_brief_version"),
    )
    op.create_index("ix_content_assets_brief", "content_assets", ["brief_id"])
    op.execute("ALTER TABLE content_assets ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON content_assets
        USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
    """)

    # Add FK from content_briefs to content_assets
    op.create_foreign_key(
        "fk_content_briefs_current_asset",
        "content_briefs",
        "content_assets",
        ["current_asset_id"],
        ["id"],
    )

    # ── llm_calls ──────────────────────────────────────────────────────────────
    op.create_table(
        "llm_calls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("prompt_key", sa.Text, nullable=False),
        sa.Column("prompt_version_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("prompt_versions.id"), nullable=True),
        sa.Column("input_tokens", sa.Integer, nullable=True),
        sa.Column("output_tokens", sa.Integer, nullable=True),
        sa.Column("cost_inr", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("cache_key", sa.Text, nullable=True),
        sa.Column("workflow_id", sa.Text, nullable=True),
        sa.Column("error_class", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_llm_calls_tenant_business", "llm_calls", ["tenant_id", "business_id"])
    op.create_index("ix_llm_calls_created_at", "llm_calls", ["created_at"])
    op.execute("ALTER TABLE llm_calls ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON llm_calls
        USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
    """)

    # ── usage_counters ─────────────────────────────────────────────────────────
    op.create_table(
        "usage_counters",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("period", sa.Text, primary_key=True, nullable=False),
        sa.Column("llm_calls_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("llm_cost_inr", sa.Numeric(12, 4), nullable=False, server_default="0"),
        sa.Column("content_briefs_generated", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.execute("ALTER TABLE usage_counters ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON usage_counters
        USING (tenant_id = current_setting('app.current_tenant', true)::uuid)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS usage_counters CASCADE")
    op.execute("DROP TABLE IF EXISTS llm_calls CASCADE")
    op.execute("DROP TABLE IF EXISTS content_assets CASCADE")
    op.execute("DROP TABLE IF EXISTS content_briefs CASCADE")
    op.execute("DROP TABLE IF EXISTS prompt_versions CASCADE")
    op.execute("DROP TYPE IF EXISTS llm_purpose")
    op.execute("DROP TYPE IF EXISTS approval_flow_type")
    op.execute("DROP TYPE IF EXISTS brief_state")
    op.execute("DROP TYPE IF EXISTS brief_type")
