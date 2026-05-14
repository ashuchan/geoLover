"""Phase 1: Identity, Tenancy & Business Profile — initial schema

Revision ID: 001_phase1_initial
Revises:
Create Date: 2026-05-14
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_phase1_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Enums ──────────────────────────────────────────────────────────────────
    op.execute("CREATE TYPE tenant_type AS ENUM ('agency', 'direct_business', 'trial')")
    op.execute(
        "CREATE TYPE user_role AS ENUM "
        "('platform_admin', 'agency_admin', 'agency_member', 'business_owner', 'business_member')"
    )
    op.execute(
        "CREATE TYPE business_status AS ENUM ('trial', 'active', 'suspended', 'deleted')"
    )
    op.execute(
        "CREATE TYPE business_source AS ENUM ('self_signup', 'agency_created', 'free_audit')"
    )
    op.execute(
        "CREATE TYPE alias_type AS ENUM "
        "('former_name', 'translit_hindi', 'translit_kannada', 'abbreviation', 'colloquial', 'auto_generated')"
    )
    op.execute(
        "CREATE TYPE keyword_source AS ENUM ('user', 'category_suggested', 'audit_discovered')"
    )
    op.execute("CREATE TYPE competitor_source AS ENUM ('user', 'audit_discovered')")
    op.execute("CREATE TYPE competitor_status AS ENUM ('tracked', 'dismissed')")

    # ── tenants ────────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", sa.Enum("agency", "direct_business", "trial", name="tenant_type"), nullable=False),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("slug", sa.String(40), nullable=False, unique=True),
        sa.Column("primary_country", sa.String(2), nullable=False, server_default="IN"),
        sa.Column("claimed_from_trial_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(slug) BETWEEN 3 AND 40", name="ck_tenants_slug_len"),
        sa.CheckConstraint("slug ~ '^[a-z0-9-]+$'", name="ck_tenants_slug_format"),
    )
    op.create_index("ix_tenants_type", "tenants", ["type"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_tenants_slug_active", "tenants", ["slug"], postgresql_where=sa.text("deleted_at IS NULL"))

    # ── users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("auth_provider_id", sa.Text, nullable=False, unique=True),
        sa.Column("email_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("email_normalized", sa.Text, nullable=False, unique=True),
        sa.Column("display_name", sa.Text, nullable=False),
        sa.Column("phone_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en-IN"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── memberships ────────────────────────────────────────────────────────────
    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=True),
        sa.Column("role", sa.Enum("platform_admin", "agency_admin", "agency_member", "business_owner", "business_member", name="user_role"), nullable=False),
        sa.Column("business_scope_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("granted_by_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "(role = 'platform_admin' AND tenant_id IS NULL) OR (role <> 'platform_admin' AND tenant_id IS NOT NULL)",
            name="ck_memberships_admin_tenant",
        ),
    )
    op.create_index(
        "ix_memberships_unique_active", "memberships",
        ["user_id", "tenant_id", "role"], unique=True,
        postgresql_where=sa.text("revoked_at IS NULL"),
    )
    op.create_index("ix_memberships_user", "memberships", ["user_id"], postgresql_where=sa.text("revoked_at IS NULL"))
    op.create_index("ix_memberships_tenant", "memberships", ["tenant_id"], postgresql_where=sa.text("revoked_at IS NULL"))

    # ── reserved_slugs ─────────────────────────────────────────────────────────
    op.create_table(
        "reserved_slugs",
        sa.Column("slug", sa.String(40), primary_key=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # Seed reserved slugs
    op.execute(
        "INSERT INTO reserved_slugs (slug, reason) VALUES "
        "('app', 'platform'), ('www', 'platform'), ('api', 'platform'), "
        "('admin', 'platform'), ('auth', 'platform'), ('static', 'platform'), "
        "('mail', 'platform'), ('support', 'platform'), ('help', 'platform'), "
        "('docs', 'platform'), ('blog', 'platform'), ('status', 'platform'), "
        "('dashboard', 'platform'), ('account', 'platform'), ('billing', 'platform'), "
        "('assets', 'platform'), ('cdn', 'platform'), ('citedby', 'platform')"
    )

    # ── categories ─────────────────────────────────────────────────────────────
    op.create_table(
        "categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.String(80), nullable=False, unique=True),
        sa.Column("parent_category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("default_keyword_suggestions", postgresql.ARRAY(sa.Text), nullable=False, server_default="{}"),
        sa.Column("default_query_template_set_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_categories_parent", "categories", ["parent_category_id"])

    # Seed Phase 1 category taxonomy
    _seed_categories()

    # ── businesses ─────────────────────────────────────────────────────────────
    op.create_table(
        "businesses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("canonical_name", sa.Text, nullable=False),
        sa.Column("name_normalized", sa.Text, nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("subcategory_ids", postgresql.ARRAY(postgresql.UUID(as_uuid=True)), nullable=False, server_default="{}"),
        sa.Column("primary_location_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("website_url", sa.Text, nullable=True),
        sa.Column("primary_email_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("primary_phone_encrypted", sa.LargeBinary, nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("locale", sa.String(10), nullable=False, server_default="en-IN"),
        sa.Column("status", sa.Enum("trial", "active", "suspended", "deleted", name="business_status"), nullable=False, server_default="trial"),
        sa.Column("source", sa.Enum("self_signup", "agency_created", "free_audit", name="business_source"), nullable=False),
        sa.Column("identity_uniqueness_score", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("length(canonical_name) BETWEEN 2 AND 200", name="ck_businesses_name_len"),
    )
    op.create_index("ix_businesses_tenant", "businesses", ["tenant_id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_businesses_tenant_status", "businesses", ["tenant_id", "status"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_businesses_name_normalized", "businesses", ["name_normalized"])

    # ── business_aliases ───────────────────────────────────────────────────────
    op.create_table(
        "business_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias_text", sa.Text, nullable=False),
        sa.Column("alias_text_normalized", sa.Text, nullable=False),
        sa.Column("alias_type", sa.Enum("former_name", "translit_hindi", "translit_kannada", "abbreviation", "colloquial", "auto_generated", name="alias_type"), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_business_aliases_business", "business_aliases", ["business_id"])
    op.create_index("ix_business_aliases_normalized", "business_aliases", ["alias_text_normalized"])

    # ── business_locations ────────────────────────────────────────────────────
    op.create_table(
        "business_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("label", sa.Text, nullable=True),
        sa.Column("city", sa.Text, nullable=False),
        sa.Column("locality", sa.Text, nullable=True),
        sa.Column("address_line_1", sa.Text, nullable=True),
        sa.Column("address_line_2", sa.Text, nullable=True),
        sa.Column("postal_code", sa.String(20), nullable=True),
        sa.Column("state", sa.Text, nullable=True),
        sa.Column("country", sa.String(2), nullable=False, server_default="IN"),
        sa.Column("geo_lat", sa.Numeric(9, 6), nullable=True),
        sa.Column("geo_lng", sa.Numeric(9, 6), nullable=True),
        sa.Column("is_primary", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_business_locations_one_primary", "business_locations", ["business_id"],
        unique=True, postgresql_where=sa.text("is_primary = true"),
    )

    # ── business_keywords ─────────────────────────────────────────────────────
    op.create_table(
        "business_keywords",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("keyword", sa.Text, nullable=False),
        sa.Column("keyword_normalized", sa.Text, nullable=False),
        sa.Column("source", sa.Enum("user", "category_suggested", "audit_discovered", name="keyword_source"), nullable=False, server_default="user"),
        sa.Column("priority", sa.Integer, nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_business_keywords_business", "business_keywords", ["business_id"])

    # ── business_competitors ──────────────────────────────────────────────────
    op.create_table(
        "business_competitors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competitor_name", sa.Text, nullable=False),
        sa.Column("competitor_name_normalized", sa.Text, nullable=False),
        sa.Column("source", sa.Enum("user", "audit_discovered", name="competitor_source"), nullable=False),
        sa.Column("discovered_in_audit_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", sa.Enum("tracked", "dismissed", name="competitor_status"), nullable=False, server_default="tracked"),
    )
    op.create_index("ix_business_competitors_business", "business_competitors", ["business_id"])

    # ── free_audit_tokens ─────────────────────────────────────────────────────
    op.create_table(
        "free_audit_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token", sa.String(64), nullable=False, unique=True),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("businesses.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_free_audit_tokens_token", "free_audit_tokens", ["token"], unique=True)
    op.create_index("ix_free_audit_tokens_business", "free_audit_tokens", ["business_id"])

    # ── admin_audit_log ────────────────────────────────────────────────────────
    op.create_table(
        "admin_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target_type", sa.Text, nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("details", postgresql.JSONB, nullable=True),
        sa.Column("ip_address", sa.Text, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_audit_log_actor", "admin_audit_log", ["actor_user_id", "created_at"])
    op.create_index("ix_audit_log_tenant", "admin_audit_log", ["tenant_id", "created_at"])

    # ── RLS policies ───────────────────────────────────────────────────────────
    _apply_rls_policies()

    # ── Triggers ───────────────────────────────────────────────────────────────
    _create_triggers()


def _apply_rls_policies() -> None:
    rls_tables = [
        "businesses",
        "business_aliases",
        "business_locations",
        "business_keywords",
        "business_competitors",
    ]
    for table in rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY {table}_tenant_read ON {table} FOR SELECT "
            f"USING (tenant_id = current_setting('app.current_tenant', true)::uuid)"
        )
        op.execute(
            f"CREATE POLICY {table}_tenant_write ON {table} FOR ALL "
            f"USING (tenant_id = current_setting('app.current_tenant', true)::uuid) "
            f"WITH CHECK (tenant_id = current_setting('app.current_tenant', true)::uuid)"
        )
        op.execute(
            f"CREATE POLICY {table}_platform_admin ON {table} FOR ALL "
            f"USING (current_setting('app.is_platform_admin', true)::boolean = true)"
        )

    # Business-scope filter for scoped roles
    op.execute(
        """
        CREATE POLICY businesses_scope_filter ON businesses FOR SELECT
        USING (
            tenant_id = current_setting('app.current_tenant', true)::uuid
            AND (
                current_setting('app.current_business_scope', true) = 'ALL'
                OR id::text = ANY(
                    string_to_array(current_setting('app.current_business_scope', true), ',')
                )
            )
        )
        """
    )


def _create_triggers() -> None:
    # Trigger 1: enforce alias tenant match
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_business_alias_tenant_match()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE
            parent_tenant_id UUID;
        BEGIN
            SELECT tenant_id INTO parent_tenant_id
            FROM businesses WHERE id = NEW.business_id;
            IF NEW.tenant_id <> parent_tenant_id THEN
                RAISE EXCEPTION 'business_alias.tenant_id must match parent business.tenant_id';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_enforce_alias_tenant
        BEFORE INSERT OR UPDATE ON business_aliases
        FOR EACH ROW EXECUTE FUNCTION enforce_business_alias_tenant_match()
        """
    )

    # Trigger 2: enforce direct_business singleton
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_direct_business_singleton()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        DECLARE
            tenant_type_val TEXT;
            existing_count INT;
        BEGIN
            SELECT type INTO tenant_type_val FROM tenants WHERE id = NEW.tenant_id FOR UPDATE;
            IF tenant_type_val = 'direct_business' THEN
                SELECT COUNT(*) INTO existing_count
                FROM businesses
                WHERE tenant_id = NEW.tenant_id
                  AND deleted_at IS NULL
                  AND id <> NEW.id;
                IF existing_count > 0 THEN
                    RAISE EXCEPTION 'direct_business tenant may only have one active business';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_enforce_direct_business_singleton
        BEFORE INSERT ON businesses
        FOR EACH ROW EXECUTE FUNCTION enforce_direct_business_singleton()
        """
    )


def _seed_categories() -> None:
    """Insert Phase 1 category taxonomy (parent + subcategories)."""
    op.execute(
        """
        INSERT INTO categories (id, name, slug, parent_category_id, default_keyword_suggestions) VALUES
        -- Top-level
        ('10000000-0000-0000-0000-000000000001', 'Professional Services', 'professional-services', NULL, '{}'),
        ('10000000-0000-0000-0000-000000000002', 'Healthcare', 'healthcare', NULL, '{}'),
        ('10000000-0000-0000-0000-000000000003', 'Education', 'education', NULL, '{}'),
        ('10000000-0000-0000-0000-000000000004', 'Real Estate', 'real-estate', NULL, '{}'),
        ('10000000-0000-0000-0000-000000000005', 'Other', 'other', NULL, '{}'),
        -- Professional Services subcategories
        ('10000001-0000-0000-0000-000000000001', 'CA Firm', 'ca-firm', '10000000-0000-0000-0000-000000000001', ARRAY['chartered accountant', 'audit services', 'tax filing', 'gst registration', 'income tax']),
        ('10000001-0000-0000-0000-000000000002', 'Law Firm', 'law-firm', '10000000-0000-0000-0000-000000000001', ARRAY['lawyer', 'legal services', 'corporate law', 'litigation', 'legal counsel']),
        ('10000001-0000-0000-0000-000000000003', 'HR Consulting', 'hr-consulting', '10000000-0000-0000-0000-000000000001', ARRAY['human resources', 'recruitment', 'payroll services', 'hr outsourcing']),
        ('10000001-0000-0000-0000-000000000004', 'Tax Consulting', 'tax-consulting', '10000000-0000-0000-0000-000000000001', ARRAY['tax consultant', 'income tax', 'gst filing', 'tax planning', 'tds']),
        ('10000001-0000-0000-0000-000000000005', 'Management Consulting', 'management-consulting', '10000000-0000-0000-0000-000000000001', ARRAY['business strategy', 'management consultant', 'process improvement']),
        ('10000001-0000-0000-0000-000000000006', 'ISO Certification', 'iso-certification', '10000000-0000-0000-0000-000000000001', ARRAY['iso 9001', 'iso certification', 'quality management', 'certification body']),
        -- Healthcare subcategories
        ('10000002-0000-0000-0000-000000000001', 'Clinic - General', 'clinic-general', '10000000-0000-0000-0000-000000000002', ARRAY['general physician', 'family doctor', 'medical clinic', 'outpatient clinic']),
        ('10000002-0000-0000-0000-000000000002', 'Clinic - Dental', 'clinic-dental', '10000000-0000-0000-0000-000000000002', ARRAY['dentist', 'dental clinic', 'teeth cleaning', 'orthodontist', 'root canal']),
        ('10000002-0000-0000-0000-000000000003', 'Clinic - Dermatology', 'clinic-dermatology', '10000000-0000-0000-0000-000000000002', ARRAY['dermatologist', 'skin clinic', 'acne treatment', 'skin specialist']),
        ('10000002-0000-0000-0000-000000000004', 'Clinic - Physiotherapy', 'clinic-physiotherapy', '10000000-0000-0000-0000-000000000002', ARRAY['physiotherapist', 'physical therapy', 'rehabilitation', 'sports injury']),
        ('10000002-0000-0000-0000-000000000005', 'Diagnostic Centre', 'diagnostic-centre', '10000000-0000-0000-0000-000000000002', ARRAY['blood test', 'pathology lab', 'diagnostic centre', 'radiology', 'mri scan']),
        ('10000002-0000-0000-0000-000000000006', 'Wellness Centre', 'wellness-centre', '10000000-0000-0000-0000-000000000002', ARRAY['wellness centre', 'holistic health', 'ayurveda', 'spa', 'meditation']),
        -- Education subcategories
        ('10000003-0000-0000-0000-000000000001', 'JEE-NEET Coaching', 'jee-neet-coaching', '10000000-0000-0000-0000-000000000003', ARRAY['jee coaching', 'neet coaching', 'iit jee', 'medical entrance', 'engineering entrance']),
        ('10000003-0000-0000-0000-000000000002', 'UPSC Coaching', 'upsc-coaching', '10000000-0000-0000-0000-000000000003', ARRAY['upsc coaching', 'ias coaching', 'civil services', 'ips preparation']),
        ('10000003-0000-0000-0000-000000000003', 'Spoken English', 'spoken-english', '10000000-0000-0000-0000-000000000003', ARRAY['spoken english', 'english speaking', 'communication skills', 'ielts coaching']),
        ('10000003-0000-0000-0000-000000000004', 'Coding & IT Training', 'coding-it-training', '10000000-0000-0000-0000-000000000003', ARRAY['coding classes', 'python training', 'web development', 'software training', 'it courses']),
        ('10000003-0000-0000-0000-000000000005', 'Yoga Studio', 'yoga-studio', '10000000-0000-0000-0000-000000000003', ARRAY['yoga classes', 'yoga studio', 'meditation', 'pranayama', 'hatha yoga']),
        -- Real Estate subcategories
        ('10000004-0000-0000-0000-000000000001', 'Real Estate Agent', 'real-estate-agent', '10000000-0000-0000-0000-000000000004', ARRAY['real estate agent', 'property dealer', 'flat for rent', 'flat for sale', 'property consultant']),
        ('10000004-0000-0000-0000-000000000002', 'Interior Designer', 'interior-designer', '10000000-0000-0000-0000-000000000004', ARRAY['interior designer', 'interior design', 'home renovation', 'modular kitchen', 'false ceiling']),
        ('10000004-0000-0000-0000-000000000003', 'Vastu Consultant', 'vastu-consultant', '10000000-0000-0000-0000-000000000004', ARRAY['vastu consultant', 'vastu shastra', 'vastu expert', 'vastu for home'])
        """
    )


def downgrade() -> None:
    # Drop triggers
    for tbl in ["business_aliases", "businesses"]:
        op.execute(f"DROP TRIGGER IF EXISTS trg_enforce_{'alias_tenant' if tbl == 'business_aliases' else 'direct_business_singleton'} ON {tbl}")

    op.execute("DROP FUNCTION IF EXISTS enforce_business_alias_tenant_match()")
    op.execute("DROP FUNCTION IF EXISTS enforce_direct_business_singleton()")

    # Drop tables (reverse dependency order)
    for tbl in [
        "admin_audit_log", "free_audit_tokens", "business_competitors",
        "business_keywords", "business_locations", "business_aliases",
        "businesses", "categories", "reserved_slugs", "memberships", "users", "tenants",
    ]:
        op.drop_table(tbl)

    # Drop enums
    for enum in [
        "competitor_status", "competitor_source", "keyword_source", "alias_type",
        "business_source", "business_status", "user_role", "tenant_type",
    ]:
        op.execute(f"DROP TYPE IF EXISTS {enum}")
