"""Phase 8: Hardening, Security Review, Launch — Ops/Admin tables

Revision ID: 008_phase8_ops
Down revision: 007_phase7_whitelabel
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "008_phase8_ops"
down_revision = "007_phase7_whitelabel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── quota_enforcement_log ──────────────────────────────────────────────────
    op.create_table(
        "quota_enforcement_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("quota_kind", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("threshold_pct", sa.Numeric(), nullable=True),
        sa.Column(
            "triggered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
    )
    op.create_index(
        "ix_quota_enforcement_log_tenant_triggered",
        "quota_enforcement_log",
        ["tenant_id", sa.text("triggered_at DESC")],
    )

    # ── tenant_grace_extensions ────────────────────────────────────────────────
    op.create_table(
        "tenant_grace_extensions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("quota_kind", sa.Text(), nullable=False),
        sa.Column("extended_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "extended_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ── impersonation_log ──────────────────────────────────────────────────────
    op.create_table(
        "impersonation_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "admin_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("impersonated_tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "impersonated_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_impersonation_log_admin_started",
        "impersonation_log",
        ["admin_user_id", sa.text("started_at DESC")],
    )

    # ── status_components ──────────────────────────────────────────────────────
    op.create_table(
        "status_components",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("health_signal_query", sa.Text(), nullable=False),
        sa.Column(
            "last_known_state",
            sa.Text(),
            nullable=False,
            server_default="operational",
        ),
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )
    # No RLS on any of these tables — they are platform admin tables


def downgrade() -> None:
    op.drop_table("status_components")
    op.drop_table("impersonation_log")
    op.drop_table("tenant_grace_extensions")
    op.drop_table("quota_enforcement_log")
