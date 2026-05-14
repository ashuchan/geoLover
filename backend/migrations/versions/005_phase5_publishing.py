"""Phase 5: Publishing & Entity Seeding

Revision ID: 005_phase5_publishing
Down revision: 004_phase4_content
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "005_phase5_publishing"
down_revision = "004_phase4_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── directory_registry (no RLS) ────────────────────────────────────────────
    op.create_table(
        "directory_registry",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("submission_method", sa.Text, nullable=False),
        sa.Column("adapter_class", sa.Text, nullable=True),
        sa.Column("verification_method", sa.Text, nullable=False),
        sa.Column("verification_config", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("known_indexed_by_ai", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_directory_registry_slug", "directory_registry", ["slug"])
    op.create_index("ix_directory_registry_active", "directory_registry", ["active"])

    # ── oauth_tokens ───────────────────────────────────────────────────────────
    op.create_table(
        "oauth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("access_token_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("refresh_token_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("wrapped_dek", sa.LargeBinary, nullable=False),
        sa.Column("kms_key_version", sa.Text, nullable=False),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scope", sa.Text, nullable=False),
        sa.Column("account_subject", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_oauth_tokens_tenant", "oauth_tokens", ["tenant_id"])
    op.create_index("ix_oauth_tokens_expires_at", "oauth_tokens", ["access_token_expires_at"])

    # Enable RLS on oauth_tokens
    op.execute("ALTER TABLE oauth_tokens ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY oauth_tokens_tenant_isolation ON oauth_tokens "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )

    # ── publish_targets ────────────────────────────────────────────────────────
    op.create_table(
        "publish_targets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("channel", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="pending_oauth"),
        sa.Column("connected_account_label", sa.Text, nullable=True),
        sa.Column("external_identifier", sa.Text, nullable=True),
        sa.Column("oauth_token_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("oauth_tokens.id"), nullable=True),
        sa.Column("publish_authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_publish_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("meta", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_publish_targets_tenant_business", "publish_targets", ["tenant_id", "business_id"])
    op.create_index("ix_publish_targets_status", "publish_targets", ["status"])

    # Enable RLS on publish_targets
    op.execute("ALTER TABLE publish_targets ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY publish_targets_tenant_isolation ON publish_targets "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )

    # ── publish_attempts ───────────────────────────────────────────────────────
    op.create_table(
        "publish_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("publish_targets.id"), nullable=False),
        sa.Column("content_asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brief_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text, nullable=False, unique=True),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("attempts_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("external_object_id", sa.Text, nullable=True),
        sa.Column("public_url", sa.Text, nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_publish_attempts_tenant_business", "publish_attempts", ["tenant_id", "business_id"])
    op.create_index("ix_publish_attempts_target", "publish_attempts", ["target_id"])
    op.create_index("ix_publish_attempts_idempotency_key", "publish_attempts", ["idempotency_key"])
    op.create_index("ix_publish_attempts_status", "publish_attempts", ["status"])

    # Enable RLS on publish_attempts
    op.execute("ALTER TABLE publish_attempts ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY publish_attempts_tenant_isolation ON publish_attempts "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )

    # ── entity_seeds ───────────────────────────────────────────────────────────
    op.create_table(
        "entity_seeds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("directory_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("directory_registry.id"), nullable=False),
        sa.Column("submission_payload", postgresql.JSONB, nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="pending_submission"),
        sa.Column("external_listing_id", sa.Text, nullable=True),
        sa.Column("external_listing_url", sa.Text, nullable=True),
        sa.Column("first_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_failures", sa.Integer, nullable=False, server_default="0"),
        sa.Column("profile_snapshot", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_entity_seeds_tenant_business", "entity_seeds", ["tenant_id", "business_id"])
    op.create_index("ix_entity_seeds_directory", "entity_seeds", ["directory_id"])
    op.create_index("ix_entity_seeds_status", "entity_seeds", ["status"])

    # Enable RLS on entity_seeds
    op.execute("ALTER TABLE entity_seeds ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY entity_seeds_tenant_isolation ON entity_seeds "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )

    # ── verification_polls ─────────────────────────────────────────────────────
    op.create_table(
        "verification_polls",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seed_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("entity_seeds.id"), nullable=True),
        sa.Column("publish_attempt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("publish_attempts.id"), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.Text, nullable=True),
        sa.Column("attempt_index", sa.Integer, nullable=False),
    )
    op.create_index("ix_verification_polls_scheduled_for", "verification_polls", ["scheduled_for"])
    op.create_index("ix_verification_polls_seed", "verification_polls", ["seed_id"])
    op.create_index("ix_verification_polls_attempt", "verification_polls", ["publish_attempt_id"])

    # Enable RLS on verification_polls
    op.execute("ALTER TABLE verification_polls ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY verification_polls_tenant_isolation ON verification_polls "
        "USING (tenant_id = current_setting('app.current_tenant')::uuid)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS verification_polls_tenant_isolation ON verification_polls")
    op.drop_table("verification_polls")

    op.execute("DROP POLICY IF EXISTS entity_seeds_tenant_isolation ON entity_seeds")
    op.drop_table("entity_seeds")

    op.execute("DROP POLICY IF EXISTS publish_attempts_tenant_isolation ON publish_attempts")
    op.drop_table("publish_attempts")

    op.execute("DROP POLICY IF EXISTS publish_targets_tenant_isolation ON publish_targets")
    op.drop_table("publish_targets")

    op.execute("DROP POLICY IF EXISTS oauth_tokens_tenant_isolation ON oauth_tokens")
    op.drop_table("oauth_tokens")

    op.drop_table("directory_registry")
