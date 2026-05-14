"""Phase 7: Whitelabel & Agency Portal

Revision ID: 007_phase7_whitelabel
Down revision: 006_phase6_notifications
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "007_phase7_whitelabel"
down_revision = "006_phase6_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enums ──────────────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE domain_type_enum AS ENUM ('platform_subdomain', 'custom')"
    )
    op.execute(
        "CREATE TYPE domain_verification_status AS ENUM ('pending', 'verified', 'failed', 'revoked')"
    )
    op.execute(
        "CREATE TYPE ssl_cert_status_enum AS ENUM ('not_required', 'provisioning', 'active', 'failed')"
    )
    op.execute(
        "CREATE TYPE email_sender_status AS ENUM ('pending_dns', 'verified', 'failed', 'revoked')"
    )
    op.execute(
        "CREATE TYPE bulk_import_status AS ENUM ('queued', 'processing', 'completed', 'failed')"
    )

    # ── theme_assets ───────────────────────────────────────────────────────────
    op.create_table(
        "theme_assets",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_kind", sa.Text(), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("gcs_object_path", sa.Text(), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=True),
        sa.Column("height_px", sa.Integer(), nullable=True),
        sa.Column("safe_for_email", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "uploaded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_theme_assets_tenant_id", "theme_assets", ["tenant_id"])

    # ── email_sender_domains ───────────────────────────────────────────────────
    op.create_table(
        "email_sender_domains",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.Text(), nullable=False, server_default="pending_dns"),
        sa.Column("dkim_selector", sa.Text(), nullable=False),
        sa.Column("dkim_public_key", sa.Text(), nullable=False),
        sa.Column("dkim_private_key_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary(), nullable=False),
        sa.Column("kms_key_version", sa.Text(), nullable=False),
        sa.Column("spf_include_status", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("dmarc_status", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("from_address", sa.Text(), nullable=False),
        sa.Column("from_friendly_name", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_health_check_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_email_sender_domains_tenant_id", "email_sender_domains", ["tenant_id"]
    )

    # ── whitelabel_configs ─────────────────────────────────────────────────────
    op.create_table(
        "whitelabel_configs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("product_display_name", sa.Text(), nullable=True),
        sa.Column("tagline", sa.Text(), nullable=True),
        sa.Column(
            "logo_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("theme_assets.id"),
            nullable=True,
        ),
        sa.Column(
            "favicon_asset_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("theme_assets.id"),
            nullable=True,
        ),
        sa.Column("primary_color_hex", sa.Text(), nullable=False, server_default="#2A6FDB"),
        sa.Column("secondary_color_hex", sa.Text(), nullable=False, server_default="#37474F"),
        sa.Column("font_family", sa.Text(), nullable=False, server_default="Inter"),
        sa.Column("support_email", sa.Text(), nullable=True),
        sa.Column(
            "customizable_strings",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "content_approval_flow",
            sa.Text(),
            nullable=False,
            server_default="agency_only",
        ),
        sa.Column(
            "sender_domain_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("email_sender_domains.id"),
            nullable=True,
        ),
        sa.Column("pdf_footer_text", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ── domain_mappings ────────────────────────────────────────────────────────
    op.create_table(
        "domain_mappings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("domain", sa.Text(), nullable=False, unique=True),
        sa.Column("domain_type", sa.Text(), nullable=False),
        sa.Column(
            "verification_status", sa.Text(), nullable=False, server_default="pending"
        ),
        sa.Column("verification_method", sa.Text(), nullable=True),
        sa.Column("verification_token", sa.Text(), nullable=True),
        sa.Column(
            "ssl_cert_status", sa.Text(), nullable=False, server_default="not_required"
        ),
        sa.Column("ssl_cert_resource_id", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ssl_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_dns_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_domain_mappings_tenant_id", "domain_mappings", ["tenant_id"])
    op.create_index(
        "ix_domain_mappings_verification_status",
        "domain_mappings",
        ["verification_status"],
    )

    # ── bulk_import_jobs ───────────────────────────────────────────────────────
    op.create_table(
        "bulk_import_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "initiated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("source", sa.Text(), nullable=False, server_default="csv_upload"),
        sa.Column("source_object_path", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("succeeded_rows", sa.Integer(), nullable=True),
        sa.Column("failed_rows", sa.Integer(), nullable=True),
        sa.Column("result_report_path", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_bulk_import_jobs_tenant_id", "bulk_import_jobs", ["tenant_id"])

    # ── branding_leak_reports ──────────────────────────────────────────────────
    op.create_table(
        "branding_leak_reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("scan_run_id", sa.Text(), nullable=False),
        sa.Column("scan_target", sa.Text(), nullable=False),
        sa.Column(
            "findings",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_branding_leak_reports_created_at", "branding_leak_reports", ["created_at"]
    )

    # ── RLS ────────────────────────────────────────────────────────────────────
    rls_tables = [
        "domain_mappings",
        "whitelabel_configs",
        "theme_assets",
        "email_sender_domains",
        "bulk_import_jobs",
    ]
    for table in rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (tenant_id = current_setting('app.current_tenant')::uuid)"
        )


def downgrade() -> None:
    rls_tables = [
        "domain_mappings",
        "whitelabel_configs",
        "theme_assets",
        "email_sender_domains",
        "bulk_import_jobs",
    ]
    for table in rls_tables:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_table("branding_leak_reports")
    op.drop_table("bulk_import_jobs")
    op.drop_table("domain_mappings")
    op.drop_table("whitelabel_configs")
    op.drop_table("email_sender_domains")
    op.drop_table("theme_assets")

    op.execute("DROP TYPE IF EXISTS bulk_import_status")
    op.execute("DROP TYPE IF EXISTS email_sender_status")
    op.execute("DROP TYPE IF EXISTS ssl_cert_status_enum")
    op.execute("DROP TYPE IF EXISTS domain_verification_status")
    op.execute("DROP TYPE IF EXISTS domain_type_enum")
