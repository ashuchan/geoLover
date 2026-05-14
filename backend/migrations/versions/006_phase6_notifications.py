"""Phase 6: Weekly Recrawl & Notifications

Revision ID: 006_phase6_notifications
Down revision: 005_phase5_publishing
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "006_phase6_notifications"
down_revision = "005_phase5_publishing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Create enums ───────────────────────────────────────────────────────────
    op.execute(
        "CREATE TYPE citation_delta_type AS ENUM ('won', 'lost', 'improved', 'declined')"
    )
    op.execute(
        "CREATE TYPE notification_priority AS ENUM ('urgent', 'standard', 'digestible')"
    )
    op.execute(
        "CREATE TYPE notification_status AS ENUM "
        "('queued', 'sending', 'delivered', 'bounced', 'failed', 'suppressed')"
    )
    op.execute(
        "CREATE TYPE notification_cadence AS ENUM "
        "('immediate', 'daily_digest', 'weekly_digest', 'only_when_active', 'off')"
    )

    # ── recrawl_schedules ──────────────────────────────────────────────────────
    op.create_table(
        "recrawl_schedules",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "business_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("businesses.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("cadence", sa.Text, nullable=False, server_default="weekly"),
        sa.Column("day_of_week", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("hour_local", sa.SmallInteger, nullable=False, server_default="6"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("algorithm_version_baseline", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_recrawl_schedules_tenant", "recrawl_schedules", ["tenant_id"])
    op.create_index(
        "ix_recrawl_schedules_bucket",
        "recrawl_schedules",
        ["day_of_week", "hour_local", "enabled"],
    )
    op.create_index(
        "ix_recrawl_schedules_next_run", "recrawl_schedules", ["next_run_at"]
    )

    op.execute("ALTER TABLE recrawl_schedules ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY recrawl_schedules_tenant_isolation ON recrawl_schedules "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )

    # ── citation_deltas ────────────────────────────────────────────────────────
    op.create_table(
        "citation_deltas",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audit_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prior_audit_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("query_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("engine", sa.Text, nullable=False),
        sa.Column("delta_type", sa.Text, nullable=False),
        sa.Column("prior_state", postgresql.JSONB, nullable=True),
        sa.Column("current_state", postgresql.JSONB, nullable=False),
        sa.Column("source_publish_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_citation_deltas_tenant_business",
        "citation_deltas",
        ["tenant_id", "business_id"],
    )
    op.create_index(
        "ix_citation_deltas_audit_run", "citation_deltas", ["audit_run_id"]
    )
    op.create_index(
        "ix_citation_deltas_delta_type", "citation_deltas", ["delta_type"]
    )

    op.execute("ALTER TABLE citation_deltas ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY citation_deltas_tenant_isolation ON citation_deltas "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )

    # ── notification_templates (no RLS) ────────────────────────────────────────
    op.create_table(
        "notification_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("template_key", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("locale", sa.Text, nullable=False, server_default="en-IN"),
        sa.Column("subject_template", sa.Text, nullable=True),
        sa.Column("body_template", sa.Text, nullable=False),
        sa.Column(
            "variables_schema",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_by_user_id",
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
    op.create_index(
        "ix_notification_templates_key_channel_locale",
        "notification_templates",
        ["template_key", "channel", "locale"],
    )
    op.create_index(
        "ix_notification_templates_active", "notification_templates", ["active"]
    )

    # ── notifications ──────────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recipient_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notification_type", sa.Text, nullable=False),
        sa.Column(
            "priority", sa.Text, nullable=False, server_default="standard"
        ),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column(
            "template_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notification_templates.id"),
            nullable=True,
        ),
        sa.Column(
            "render_payload",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("send_attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suppression_reason", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_notifications_tenant_user",
        "notifications",
        ["tenant_id", "recipient_user_id"],
    )
    op.create_index(
        "ix_notifications_idempotency_key", "notifications", ["idempotency_key"]
    )
    op.create_index("ix_notifications_status", "notifications", ["status"])
    op.create_index(
        "ix_notifications_created_at", "notifications", ["created_at"]
    )

    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY notifications_tenant_isolation ON notifications "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )

    # ── notification_preferences ───────────────────────────────────────────────
    op.create_table(
        "notification_preferences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.Text, nullable=False),
        sa.Column("cadence", sa.Text, nullable=False, server_default="immediate"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "user_id",
            "tenant_id",
            "notification_type",
            name="uq_notif_pref_user_tenant_type",
        ),
    )
    op.execute(
        "ALTER TABLE notification_preferences ADD COLUMN channels_enabled TEXT[] NOT NULL DEFAULT '{}'"
    )
    op.create_index(
        "ix_notification_preferences_user_tenant",
        "notification_preferences",
        ["user_id", "tenant_id"],
    )

    op.execute("ALTER TABLE notification_preferences ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY notification_preferences_tenant_isolation ON notification_preferences "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )

    # ── outbound_delivery_log (no RLS) ─────────────────────────────────────────
    op.create_table(
        "outbound_delivery_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "notification_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("notifications.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("provider_message_id", sa.Text, nullable=True),
        sa.Column("event", sa.Text, nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_details", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_outbound_delivery_log_notification",
        "outbound_delivery_log",
        ["notification_id"],
    )
    op.create_index(
        "ix_outbound_delivery_log_event_time",
        "outbound_delivery_log",
        ["event_time"],
    )

    # ── bounced_addresses (no RLS) ─────────────────────────────────────────────
    op.create_table(
        "bounced_addresses",
        sa.Column("email_normalized", sa.Text, primary_key=True),
        sa.Column("bounce_type", sa.Text, nullable=False),
        sa.Column(
            "bounced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("cleared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_bounced_addresses_bounced_at", "bounced_addresses", ["bounced_at"]
    )


def downgrade() -> None:
    op.drop_table("bounced_addresses")
    op.drop_table("outbound_delivery_log")

    op.execute(
        "DROP POLICY IF EXISTS notification_preferences_tenant_isolation ON notification_preferences"
    )
    op.drop_table("notification_preferences")

    op.execute(
        "DROP POLICY IF EXISTS notifications_tenant_isolation ON notifications"
    )
    op.drop_table("notifications")

    op.drop_table("notification_templates")

    op.execute(
        "DROP POLICY IF EXISTS citation_deltas_tenant_isolation ON citation_deltas"
    )
    op.drop_table("citation_deltas")

    op.execute(
        "DROP POLICY IF EXISTS recrawl_schedules_tenant_isolation ON recrawl_schedules"
    )
    op.drop_table("recrawl_schedules")

    op.execute("DROP TYPE IF EXISTS notification_cadence")
    op.execute("DROP TYPE IF EXISTS notification_status")
    op.execute("DROP TYPE IF EXISTS notification_priority")
    op.execute("DROP TYPE IF EXISTS citation_delta_type")
