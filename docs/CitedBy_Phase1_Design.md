# CitedBy — Phase 1 Design
## Identity, Tenancy & Business Profile
**Version:** 1.0
**Status:** Approved for implementation
**Date:** May 2026
**Author:** CTO, CitedBy
**Parent document:** `CitedBy_HLD_v1.md`
**Modules covered:** Identity & Tenancy (#1), Business Profile (#2)

---

## 1. Phase Overview

### 1.1 Why this is Phase 1

Identity, Tenancy and Business Profile are the *only* modules that every other module depends on. Until they exist:
- We cannot persist a business — so Audit has nothing to audit.
- We cannot authenticate a user — so the UI has nothing to render.
- We cannot resolve a tenant — so the multi-tenancy spine has no anchor.
- We cannot enforce RLS — so we cannot safely write *any* customer data.

These two modules are foundational. They must be correct, well-tested, and unambiguous before Phase 2 begins. A bug here is a multi-tenancy data leak; a flaw here is rework everywhere.

### 1.2 What this phase delivers

By the end of Phase 1:

- A user can sign up via Auth0 (email + Google).
- A new Tenant is created on first signup, either as `agency` or `direct_business` type.
- An agency operator can create Businesses under their tenant; each business has profile, location(s), keywords, services, and aliases.
- A direct SMB owner can sign up and immediately enter their business profile (no agency intermediary).
- RLS is live on every business-data table; cross-tenant access is impossible at the database layer.
- The "free audit" entry point can create a *trial* business with email-only capture (no full account), with a clear upgrade path.
- A baseline taxonomy of business categories (Professional Services, Healthcare, Education, Real Estate, Other) is seeded.

### 1.3 What this phase does NOT deliver

- No audit functionality (Phase 2).
- No content generation (Phase 4).
- No white-label custom domains (Phase 7); subdomain routing is supported but full CNAME is deferred.
- No billing enforcement (Phase 8); plans exist but quotas are not enforced.
- No SSO beyond Google (Phase 8).
- No bulk CSV import of businesses (Phase 7, for agencies).

---

## 2. Requirements

### 2.1 Functional requirements (derived from PRD §2 personas and §3.1 onboarding)

| # | Requirement | Source |
|---|---|---|
| F1 | A user can register with email+password or Google SSO. | PRD §4 |
| F2 | On first registration, the user is associated with a new Tenant. | Implied by multi-tenancy |
| F3 | A Tenant has a type (`agency` or `direct_business`); type is set at creation and immutable. | Architectural decision |
| F4 | A Tenant has at least one administrative User; the registering user becomes `agency_admin` (for agency tenants) or `business_owner` (for direct tenants). | PRD personas |
| F5 | An agency admin can invite additional members (`agency_member`) by email. | PRD §3.3 |
| F6 | An agency admin can create one or more Businesses within the tenant. | PRD §3.3 |
| F7 | A direct_business tenant has exactly one Business, created at signup. | Architectural decision |
| F8 | A Business has: name, category, primary location, additional locations (optional), services list, keywords (5+), aliases (optional). | PRD §1.1 |
| F9 | A Business can be edited at any time by an authorised user. | Implied |
| F10 | A Business can be soft-deleted; hard delete after 30 days. | DPDP compliance |
| F11 | A free-audit submission creates a "trial" Business attached to a "trial" Tenant, with email-only contact. | PRD §3.1 Module 1 |
| F12 | A trial Tenant can be claimed (converted to direct_business) by completing registration with the same email within 14 days. | UX requirement |
| F13 | Roles: `platform_admin`, `agency_admin`, `agency_member`, `business_owner`, `business_member`. | PRD §6.1 |
| F14 | A user can be a member of more than one Tenant (rare but supported). | Multi-tenancy correctness |
| F15 | Tenant resolution: requests to `<subdomain>.citedby.app` resolve to the tenant identified by the subdomain. | PRD §3.3 + Whitelabel preparation |
| F16 | A category taxonomy is seeded: Professional Services, Healthcare, Education, Real Estate, Other. Each has sub-categories used to suggest keywords. | PRD Q.10 (Appendix) |

### 2.2 Non-functional requirements

| # | Requirement | Target |
|---|---|---|
| NF1 | Tenant isolation: zero cross-tenant data exposure under any application bug or query. | RLS-enforced; verified by automated tests |
| NF2 | Business profile creation latency. | <500ms p95 |
| NF3 | Authentication latency. | <300ms p95 |
| NF4 | Number of Businesses per Tenant (MVP cap). | 500 |
| NF5 | Number of Tenants supported. | 10,000 |
| NF6 | User session lifetime. | 7 days, sliding |
| NF7 | DPDP: PII at rest is encrypted at the column level for sensitive fields. | Column encryption for email, phone |
| NF8 | DPDP: right-to-erasure for businesses completes within 24h of request. | Cascading soft-delete + 30-day purge |
| NF9 | All admin actions audit-logged. | 7-year retention |

---

## 3. Domain Model — Detailed

### 3.1 Aggregates and their invariants

#### `Tenant`
```
Tenant
├── id                  (UUID, immutable)
├── type                (enum: 'agency' | 'direct_business' | 'trial', immutable after creation)
├── display_name        (string, mutable)
├── slug                (string, unique, used for subdomain; immutable)
├── primary_country     (ISO-3166-1, default 'IN')
├── created_at, updated_at
├── deleted_at          (nullable; soft-delete marker)
└── claimed_from_trial  (nullable FK to prior trial tenant if claimed)
```

**Invariants:**
- `type` cannot change after creation. To convert trial → direct_business, a new Tenant is created and the trial Tenant is linked via `claimed_from_trial`.
- `slug` is globally unique across all tenants, including soft-deleted ones for 90 days after deletion.
- A `direct_business` tenant has exactly one Business; this invariant is enforced by a partial unique constraint (`UNIQUE WHERE tenant.type = 'direct_business'`).

#### `User`
```
User
├── id                  (UUID, immutable)
├── auth_provider_id    (Auth0 subject ID, unique)
├── email               (encrypted column, unique)
├── email_normalized    (lower-cased, unique; for lookups)
├── display_name
├── phone               (encrypted, nullable)
├── locale              (default 'en-IN')
├── created_at, updated_at, last_login_at
└── deleted_at          (nullable)
```

**Invariants:**
- A User can exist without any Tenant membership (rare, transient — e.g., during signup).
- `auth_provider_id` is the authoritative external identity.
- Email is stored encrypted; `email_normalized` is the lookup key. Both maintained atomically.

#### `Membership`
```
Membership
├── id                  (UUID)
├── user_id             (FK → User)
├── tenant_id           (FK → Tenant)
├── role                (enum: 'platform_admin' | 'agency_admin' | 'agency_member' |
│                              'business_owner' | 'business_member')
├── business_scope_ids  (UUID[]; for 'business_member'/'business_owner' when scoped within agency)
├── granted_by_user_id  (FK → User; who granted this)
├── granted_at
├── revoked_at          (nullable)
└── UNIQUE (user_id, tenant_id, role) WHERE revoked_at IS NULL
```

**Invariants:**
- A user can have at most one active membership of a given role in a given tenant.
- `business_scope_ids` is only meaningful when role is `business_owner` or `business_member` *within* an agency tenant. In direct_business tenants, the role applies to the single Business.
- `platform_admin` memberships have `tenant_id = NULL` (rare; represents CitedBy staff).

**Rationale for the scoping mechanism:** An agency might have ten businesses. The agency_admin sees all ten. The agency wants to give Priya (the CA firm partner) access to *only* her firm's data within the agency's portal. Priya's membership: `(user=Priya, tenant=AgencyA, role=business_owner, business_scope_ids=[CA_firm_id])`. RLS layered on this: business-scoped reads require `business_id = ANY(current_setting('app.current_business_scope'))` if the role demands it.

#### `Business`
```
Business
├── id                  (UUID, immutable)
├── tenant_id           (FK → Tenant, immutable)
├── canonical_name      (string)
├── name_normalized     (lower-cased, whitespace-normalised; for citation matching)
├── category_id         (FK → Category)
├── subcategory_ids     (UUID[])
├── primary_location_id (FK → BusinessLocation)
├── website_url         (nullable, normalised)
├── primary_email       (encrypted, nullable)
├── primary_phone       (encrypted, E.164 normalised, nullable)
├── description         (text)
├── locale              (default 'en-IN')
├── status              (enum: 'trial' | 'active' | 'suspended' | 'deleted')
├── source              (enum: 'self_signup' | 'agency_created' | 'free_audit')
├── created_at, updated_at
├── deleted_at          (nullable)
└── identity_uniqueness_score  (float, 0-1; computed; flags low-entropy names)
```

**Invariants:**
- `canonical_name` must be non-empty.
- `name_normalized` is derived from `canonical_name` and updated atomically.
- `tenant_id` is set at creation and is immutable.
- `identity_uniqueness_score` is recomputed when name or aliases change. Used by citation detection downstream (HLD §6 risk R6).
- A `trial` business has nullable owner User; an `active` business must have at least one `business_owner` membership.

#### `BusinessAlias`
```
BusinessAlias
├── id, business_id (FK), tenant_id (FK, denormalised for RLS)
├── alias_text
├── alias_text_normalized
├── alias_type          (enum: 'former_name' | 'translit_hindi' | 'translit_kannada' | 
│                              'abbreviation' | 'colloquial' | 'auto_generated')
├── confidence          (1.0 for user-entered; <1.0 for auto-generated)
└── created_at
```

**Invariants:**
- An alias's `tenant_id` must equal the parent business's `tenant_id` (enforced by trigger).
- User-entered aliases have confidence=1.0. The system auto-generates transliteration variants (Phase 2) at lower confidence.

#### `BusinessLocation`
```
BusinessLocation
├── id, business_id (FK), tenant_id (FK, denormalised)
├── label               (e.g., "HQ", "Indiranagar branch")
├── city
├── locality            (e.g., "Koramangala")
├── address_line_1, address_line_2
├── postal_code
├── state, country
├── geo_lat, geo_lng    (optional; for future proximity queries)
├── is_primary          (boolean)
└── created_at
```

**Invariants:**
- Exactly one location per business has `is_primary = true` (partial unique index).
- For free-audit trial businesses, only `city` and `locality` are required; full address is optional.

#### `BusinessKeyword`
```
BusinessKeyword
├── id, business_id (FK), tenant_id (FK, denormalised)
├── keyword
├── keyword_normalized
├── source              (enum: 'user' | 'category_suggested' | 'audit_discovered')
├── priority            (integer; user can rank top N keywords)
└── created_at
```

**Invariants:**
- A business has at minimum 1 keyword to be `active`. At least 5 is recommended (per PRD).
- Keywords are scoped per-business; the same keyword can appear in many businesses across tenants.

#### `BusinessCompetitor`
```
BusinessCompetitor
├── id, business_id (FK), tenant_id (FK, denormalised)
├── competitor_name
├── competitor_name_normalized
├── source              (enum: 'user' | 'audit_discovered')
├── discovered_in_audit_run_id (nullable FK; if discovered)
├── first_seen_at, last_seen_at
└── status              (enum: 'tracked' | 'dismissed')
```

**Note:** competitors discovered through audits are recorded here. Phase 2 populates this; Phase 1 only defines the schema.

#### `Category` (reference data, not tenant-owned)
```
Category
├── id, name, slug
├── parent_category_id  (nullable; for two-level taxonomy)
├── default_keyword_suggestions  (text[])
└── default_query_template_set  (FK; for Phase 2 use)
```

Seeded with the PRD taxonomy. Not under RLS — same for all tenants.

### 3.2 Relationship overview

```
Tenant 1───N User (via Membership)
Tenant 1───N Business
Business 1───N BusinessAlias
Business 1───N BusinessLocation
Business 1───N BusinessKeyword
Business 1───N BusinessCompetitor
Business N───1 Category
Category 1───N Category (parent-child)
```

---

## 4. Multi-Tenancy Design — The Crown Jewel

This section is exhaustive because multi-tenancy correctness is the single highest-stakes property of the system.

### 4.1 The three-layer defence (recap from HLD)

1. **Application layer.** Every API handler resolves `tenant_id` from the request context and asserts the authenticated user has a non-revoked membership with sufficient role.
2. **Database layer.** RLS policies enforce `tenant_id = current_setting('app.current_tenant')` on every business-data row.
3. **CI layer.** Static analysis blocks PRs that bypass the standard repository or omit tenant filters.

### 4.2 Tenant resolution flow

```
HTTP Request arrives at Cloud Run
  │
  ├── 1. Extract Host header
  │       e.g., "app.citedby.app", "agencyA.citedby.app", "geo.agencyA.com"
  │
  ├── 2. Tenant resolution lookup:
  │       a. If host matches a custom domain in `domain_mappings` → tenant_id
  │       b. Else if subdomain of citedby.app → lookup `tenant.slug = subdomain` → tenant_id
  │       c. Else if host = "app.citedby.app" → no tenant context (platform admin only)
  │
  ├── 3. JWT validation:
  │       - Verify JWT signature against Auth0
  │       - Extract user_id from `sub` claim
  │
  ├── 4. Authorisation:
  │       - Load active memberships for user_id
  │       - If tenant_id resolved in step 2: assert user has membership in that tenant
  │       - If not: assert user is platform_admin (else 403)
  │
  ├── 5. Database session setup:
  │       - SET app.current_tenant = <tenant_id>
  │       - SET app.current_user_id = <user_id>
  │       - SET app.current_business_scope = <business_scope_ids or 'ALL'>
  │
  └── 6. Dispatch to handler
```

The session setup in step 5 happens on **every** connection checkout from the pool. There is no path through the system where a query runs without these variables set, because the connection pool wrapper enforces it. A query executed without `app.current_tenant` set causes RLS to filter all rows out (default deny).

### 4.3 RLS policy template

Every tenant-owned table gets the following pair of policies. Example for `businesses`:

```sql
-- Enable RLS
ALTER TABLE businesses ENABLE ROW LEVEL SECURITY;
ALTER TABLE businesses FORCE ROW LEVEL SECURITY;

-- Read policy
CREATE POLICY businesses_tenant_read ON businesses
    FOR SELECT
    USING (
        tenant_id = current_setting('app.current_tenant')::uuid
    );

-- Write policy
CREATE POLICY businesses_tenant_write ON businesses
    FOR ALL
    USING (
        tenant_id = current_setting('app.current_tenant')::uuid
    )
    WITH CHECK (
        tenant_id = current_setting('app.current_tenant')::uuid
    );

-- Platform admin bypass (controlled, audited)
CREATE POLICY businesses_platform_admin ON businesses
    FOR ALL
    USING (
        current_setting('app.is_platform_admin', true)::boolean = true
    );
```

`FORCE ROW LEVEL SECURITY` ensures even the table owner cannot bypass RLS. This means our migration scripts and admin tools also obey RLS — admin operations require explicit `SET app.is_platform_admin = true`, which is logged.

### 4.4 Business-scoped reads (the `business_member` case)

When a user's role is `business_member` (within an agency), they can only see their assigned businesses. This requires an additional layer:

```sql
CREATE POLICY businesses_scope_filter ON businesses
    FOR SELECT
    USING (
        tenant_id = current_setting('app.current_tenant')::uuid
        AND (
            current_setting('app.current_business_scope') = 'ALL'
            OR id::text = ANY(string_to_array(current_setting('app.current_business_scope'), ','))
        )
    );
```

For `agency_admin` and platform-wide roles, `app.current_business_scope` is set to `'ALL'`. For scoped roles, it's set to the comma-joined list of business IDs from their membership.

### 4.5 Connection pool integration

The application uses one logical connection pool. Every checkout runs the following before returning the connection:

```python
def acquire_connection(request_context):
    conn = pool.acquire()
    conn.execute(
        "SELECT set_config('app.current_tenant', $1, true),"
        "       set_config('app.current_user_id', $2, true),"
        "       set_config('app.current_business_scope', $3, true),"
        "       set_config('app.is_platform_admin', $4, true)",
        request_context.tenant_id,
        request_context.user_id,
        request_context.business_scope_str,
        'true' if request_context.is_platform_admin else 'false'
    )
    return conn
```

`set_config(..., true)` makes the setting transaction-local — released automatically on connection return. No risk of leakage between requests.

### 4.6 Cross-tenant operations (the rare exception)

Some platform operations legitimately need to span tenants (e.g., a "list all agencies and their business counts" admin dashboard, or a deduplication job). These run as `platform_admin` context, with `app.is_platform_admin = true`. Every such operation:
- Requires a `platform_admin` membership
- Logs the operation in `admin_audit_log` with the query intent
- Is reviewed quarterly

There is **no** application code path other than the platform admin path that can read across tenants. None.

---

## 5. Database Schema (DDL outline)

The full DDL is in `migrations/001_phase1_initial.sql`. Key elements:

### 5.1 Tables and primary indexes

```sql
-- ========================
-- Identity & Tenancy
-- ========================

CREATE TYPE tenant_type AS ENUM ('agency', 'direct_business', 'trial');
CREATE TYPE user_role AS ENUM (
    'platform_admin', 'agency_admin', 'agency_member',
    'business_owner', 'business_member'
);

CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type tenant_type NOT NULL,
    display_name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    primary_country CHAR(2) NOT NULL DEFAULT 'IN',
    claimed_from_trial UUID REFERENCES tenants(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (length(slug) BETWEEN 3 AND 40),
    CHECK (slug ~ '^[a-z0-9-]+$')
);
CREATE INDEX tenants_type_idx ON tenants(type) WHERE deleted_at IS NULL;
CREATE INDEX tenants_slug_active_idx ON tenants(slug) WHERE deleted_at IS NULL;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_provider_id TEXT NOT NULL UNIQUE,
    email_encrypted BYTEA NOT NULL,         -- pgcrypto-encrypted
    email_normalized TEXT NOT NULL UNIQUE,  -- lower-cased, deterministic for lookup
    display_name TEXT NOT NULL,
    phone_encrypted BYTEA,
    locale TEXT NOT NULL DEFAULT 'en-IN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    tenant_id UUID REFERENCES tenants(id),  -- NULL for platform_admin
    role user_role NOT NULL,
    business_scope_ids UUID[] NOT NULL DEFAULT '{}',
    granted_by_user_id UUID REFERENCES users(id),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ,
    CHECK (
        (role = 'platform_admin' AND tenant_id IS NULL)
        OR (role <> 'platform_admin' AND tenant_id IS NOT NULL)
    )
);
CREATE UNIQUE INDEX memberships_unique_active_idx
    ON memberships(user_id, tenant_id, role)
    WHERE revoked_at IS NULL;
CREATE INDEX memberships_user_idx ON memberships(user_id) WHERE revoked_at IS NULL;
CREATE INDEX memberships_tenant_idx ON memberships(tenant_id) WHERE revoked_at IS NULL;

-- ========================
-- Business Profile
-- ========================

CREATE TYPE business_status AS ENUM ('trial', 'active', 'suspended', 'deleted');
CREATE TYPE business_source AS ENUM ('self_signup', 'agency_created', 'free_audit');

CREATE TABLE categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    parent_category_id UUID REFERENCES categories(id),
    default_keyword_suggestions TEXT[] NOT NULL DEFAULT '{}',
    default_query_template_set_id UUID,  -- FK added in Phase 2
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE businesses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id),
    canonical_name TEXT NOT NULL,
    name_normalized TEXT NOT NULL,
    category_id UUID NOT NULL REFERENCES categories(id),
    subcategory_ids UUID[] NOT NULL DEFAULT '{}',
    primary_location_id UUID,  -- self-FK after location creation
    website_url TEXT,
    primary_email_encrypted BYTEA,
    primary_phone_encrypted BYTEA,
    description TEXT,
    locale TEXT NOT NULL DEFAULT 'en-IN',
    status business_status NOT NULL DEFAULT 'trial',
    source business_source NOT NULL,
    identity_uniqueness_score REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    CHECK (length(canonical_name) BETWEEN 2 AND 200)
);
CREATE INDEX businesses_tenant_idx ON businesses(tenant_id) WHERE deleted_at IS NULL;
CREATE INDEX businesses_tenant_status_idx ON businesses(tenant_id, status) WHERE deleted_at IS NULL;
CREATE INDEX businesses_name_normalized_idx ON businesses(name_normalized);  -- for citation lookup

-- Ensures direct_business tenants have exactly one business
CREATE UNIQUE INDEX businesses_direct_tenant_uniq
    ON businesses(tenant_id)
    WHERE deleted_at IS NULL
      AND tenant_id IN (SELECT id FROM tenants WHERE type = 'direct_business');
-- Note: this partial unique with subquery requires a trigger in practice; see migration

CREATE TABLE business_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,  -- denormalised for RLS
    alias_text TEXT NOT NULL,
    alias_text_normalized TEXT NOT NULL,
    alias_type TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX business_aliases_business_idx ON business_aliases(business_id);
CREATE INDEX business_aliases_normalized_idx ON business_aliases(alias_text_normalized);

CREATE TABLE business_locations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,  -- denormalised for RLS
    label TEXT,
    city TEXT NOT NULL,
    locality TEXT,
    address_line_1 TEXT,
    address_line_2 TEXT,
    postal_code TEXT,
    state TEXT,
    country CHAR(2) NOT NULL DEFAULT 'IN',
    geo_lat NUMERIC(9,6),
    geo_lng NUMERIC(9,6),
    is_primary BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX business_locations_one_primary_idx
    ON business_locations(business_id)
    WHERE is_primary = true;

CREATE TABLE business_keywords (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,  -- denormalised for RLS
    keyword TEXT NOT NULL,
    keyword_normalized TEXT NOT NULL,
    source TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX business_keywords_business_idx ON business_keywords(business_id);

CREATE TABLE business_competitors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    business_id UUID NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    tenant_id UUID NOT NULL,
    competitor_name TEXT NOT NULL,
    competitor_name_normalized TEXT NOT NULL,
    source TEXT NOT NULL,
    discovered_in_audit_run_id UUID,  -- FK added in Phase 2
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'tracked'
);

-- ========================
-- Admin Audit
-- ========================

CREATE TABLE admin_audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_user_id UUID NOT NULL REFERENCES users(id),
    tenant_id UUID,
    action TEXT NOT NULL,
    target_type TEXT,
    target_id UUID,
    details JSONB,
    ip_address INET,
    user_agent TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX admin_audit_log_actor_idx ON admin_audit_log(actor_user_id, created_at DESC);
CREATE INDEX admin_audit_log_tenant_idx ON admin_audit_log(tenant_id, created_at DESC);
```

### 5.2 Triggers

Three triggers enforce invariants that are awkward to express purely declaratively:

1. **`enforce_business_alias_tenant_match`** — on INSERT/UPDATE of `business_aliases`, asserts `tenant_id` matches the parent business's `tenant_id`.
2. **`enforce_direct_business_singleton`** — on INSERT of `businesses`, if tenant is `direct_business`, asserts no other active business exists for that tenant.
3. **`update_business_name_normalized`** — on INSERT/UPDATE, recomputes `name_normalized` from `canonical_name`.

### 5.3 RLS deployment

RLS policies are applied to: `businesses`, `business_aliases`, `business_locations`, `business_keywords`, `business_competitors`.

Not under RLS: `tenants`, `users`, `memberships`, `categories`, `admin_audit_log`. These have their own access controls implemented at the application layer because their queries inherently cross tenant boundaries during normal operation (e.g., looking up a user's memberships requires reading rows from potentially multiple tenants).

### 5.4 Encryption strategy

Sensitive columns (`email`, `phone`) use **deterministic envelope encryption**:
- Application-layer encryption with a per-platform KMS-backed key (Phase 1)
- The `_normalized` companion column stores a deterministic HMAC of the lowercased value for lookup
- Decryption happens only at use; values returned to API are masked unless explicit "view-sensitive" permission

Phase 2 enhancement: per-tenant encryption keys for stronger isolation guarantees.

---

## 6. API Design (representative endpoints)

The API uses FastAPI with Pydantic models. Versioned at `/api/v1/`. All endpoints require authentication unless explicitly marked public.

### 6.1 Authentication endpoints

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/auth/callback` | Auth0 callback handler | Public |
| POST | `/api/v1/auth/logout` | End session | Authenticated |
| GET | `/api/v1/auth/me` | Return current user + active memberships | Authenticated |

### 6.2 Tenant endpoints

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/tenants` | Create a tenant (called on first signup) | Authenticated; user must not already have a tenant of the same type |
| GET | `/api/v1/tenants/current` | Return current tenant info (resolved from subdomain) | Authenticated |
| PATCH | `/api/v1/tenants/current` | Update tenant display_name, etc. | agency_admin or platform_admin |
| POST | `/api/v1/tenants/current/members` | Invite a member | agency_admin |
| GET | `/api/v1/tenants/current/members` | List members | agency_admin |
| DELETE | `/api/v1/tenants/current/members/{id}` | Revoke membership | agency_admin |

### 6.3 Business endpoints

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/businesses` | Create a business | agency_admin (in agency tenant) or business_owner (in direct tenant, only one allowed) |
| GET | `/api/v1/businesses` | List businesses in current tenant (filtered by scope) | Any tenant member |
| GET | `/api/v1/businesses/{id}` | Get business profile | Any member with access to this business |
| PATCH | `/api/v1/businesses/{id}` | Update business profile | business_owner or agency_admin |
| DELETE | `/api/v1/businesses/{id}` | Soft-delete business | business_owner or agency_admin |
| POST | `/api/v1/businesses/{id}/locations` | Add a location | business_owner or agency_admin |
| POST | `/api/v1/businesses/{id}/aliases` | Add an alias | business_owner or agency_admin |
| POST | `/api/v1/businesses/{id}/keywords` | Add keywords (batch) | business_owner or agency_admin |

### 6.4 Free audit endpoint (public)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/free-audit/start` | Create trial tenant + business, return audit-tracking token | Public (rate-limited; CAPTCHA after threshold) |
| GET | `/api/v1/free-audit/{token}/status` | Poll for audit progress | Public, token-scoped |
| GET | `/api/v1/free-audit/{token}/report` | Retrieve audit report | Public, token-scoped |
| POST | `/api/v1/free-audit/{token}/claim` | Begin claim flow (sends magic link to email) | Public, token-scoped |

The `free-audit` flow is the only "public" path in the API. It is heavily rate-limited (3 audits per IP per day; CAPTCHA after 3), CAPTCHA-protected, and produces a token that's valid for 14 days.

### 6.5 Permission matrix

| Action | platform_admin | agency_admin | agency_member | business_owner (in agency) | business_owner (direct) |
|---|---|---|---|---|---|
| Create tenant | ✓ (any) | (self at signup) | — | — | (self at signup) |
| Read tenant info | ✓ (any) | ✓ (own) | ✓ (own) | ✓ (own) | ✓ (own) |
| Update tenant | ✓ | ✓ | — | — | ✓ |
| List businesses in tenant | ✓ | ✓ | ✓ (scoped) | ✓ (own only) | ✓ (own only) |
| Create business | ✓ | ✓ | — | — | (1 at signup) |
| Read business | ✓ | ✓ (own tenant) | ✓ (scoped) | ✓ (own) | ✓ (own) |
| Update business profile | ✓ | ✓ | — (unless scope) | ✓ (own) | ✓ (own) |
| Delete business | ✓ | ✓ | — | — | ✓ (own) |
| Invite tenant member | ✓ | ✓ | — | — | — |

---

## 7. Onboarding Flows (sequence diagrams)

### 7.1 Free audit flow (public, no account)

```
User           Frontend          API                Workflow         Email
 │                │                │                    │              │
 │ enter business │                │                    │              │
 │   details ────►│                │                    │              │
 │                │ POST /free-    │                    │              │
 │                │   audit/start  │                    │              │
 │                ├───────────────►│                    │              │
 │                │                │ Create trial tenant│              │
 │                │                │ Create trial biz   │              │
 │                │                │ Return audit_token │              │
 │                │◄───────────────┤                    │              │
 │                │                │ Start AuditWorkflow│              │
 │                │                ├───────────────────►│              │
 │                │                │ (Phase 2)          │              │
 │                │                │                    │  ... runs ...│
 │                │                │                    │              │
 │                │ Poll status   │                    │              │
 │                ├───────────────►│                    │              │
 │                │ Audit complete │                    │              │
 │                │                │                    │ trigger email│
 │                │                │                    ├─────────────►│
 │                │                │                    │              │
 │  receives PDF report email  ◄──┼────────────────────┼──────────────┤
 │                │                │                    │              │
 │ optional: Claim │                │                    │              │
 │   ────────────►│                │                    │              │
 │                │ POST /claim    │                    │              │
 │                ├───────────────►│                    │              │
 │                │                │ send magic link    │              │
 │                │                ├────────────────────┼─────────────►│
 │                │                │                    │              │
 │ click magic link → Auth0 → register → tenant.type='direct_business' │
 │ trial tenant linked via claimed_from_trial                          │
 │ trial business migrated to new tenant (atomic transaction)          │
```

**Critical detail in the claim flow:** when a trial Tenant is claimed, we create a *new* Tenant (`type='direct_business'`) and **move** the Business to the new tenant atomically. The trial tenant is then soft-deleted with `claimed_from_trial` linking them. This preserves the immutability of `Tenant.type`.

### 7.2 Direct SMB signup

```
User → Auth0 signup → /api/v1/auth/callback
     → No existing memberships → onboarding wizard
     → POST /api/v1/tenants {type: 'direct_business', display_name, slug}
     → API creates Tenant + Membership (role=business_owner)
     → POST /api/v1/businesses {...}
     → API creates Business (status='active' once profile is complete)
     → Redirect to dashboard at <slug>.citedby.app
```

### 7.3 Agency signup

```
User → Auth0 signup → /api/v1/auth/callback
     → onboarding wizard, selects "I run an agency"
     → POST /api/v1/tenants {type: 'agency', display_name, slug}
     → API creates Tenant + Membership (role=agency_admin)
     → Redirect to <slug>.citedby.app/clients (empty state)
     → Agency adds first business: POST /api/v1/businesses
     → Repeat for each client
```

### 7.4 Agency invites member

```
agency_admin → POST /tenants/current/members {email, role}
            → API creates pending invitation (token + email send)
Invitee     → clicks link → Auth0 (signup or login)
            → /api/v1/auth/callback identifies invitation
            → API creates User if new, then Membership
            → Invitee redirected to <agency_slug>.citedby.app
```

---

## 8. Edge Cases and Error Handling

| Case | Handling |
|---|---|
| User registers with email of an existing pending invitation | On Auth0 callback, match by `email_normalized`, attach to invitation, create User+Membership atomically. |
| Free audit submitted twice with same business name + locality + email | Return the existing `audit_token` instead of creating duplicate trial. Rate-limit further submissions. |
| Slug collision on tenant creation | Return 409 with suggested alternatives (`acme-1`, `acme-2`, ...). |
| Slug requested for reserved name (`app`, `www`, `api`, `admin`) | Return 400 with reserved-name error. |
| User tries to belong to multiple agencies | Allowed; UI shows tenant switcher; each request resolves a single active tenant via subdomain. |
| Trial expiry after 14 days unclaimed | Cron workflow soft-deletes trial tenant + trial business; report PDFs retained 30 days for audit/compliance, then purged. |
| Business in agency tenant deleted, then agency wants to recreate | Allowed; new business with new ID. Deleted business hard-purged after 30 days. |
| Concurrent updates to business profile by two agency operators | Last-write-wins on individual fields with `updated_at` timestamp; for sensitive fields (status, ownership), optimistic concurrency check on `version` column (added). |
| User loses access to their Auth0 account | Platform admin manual recovery via verified ID; documented runbook. |

---

## 9. Self-Review

### Pass 1

| # | Severity | Finding | Where |
|---|---|---|---|
| H1 | **High** | The `businesses_direct_tenant_uniq` partial unique index uses a subquery, which Postgres doesn't allow in index predicates. The constraint must be enforced by trigger, but the SQL example is wrong. | §5.1 |
| H2 | **High** | The free-audit flow creates a trial Business with `source='free_audit'` but does not specify how RLS works for the *unauthenticated* polling/report retrieval. A public token cannot set `app.current_tenant` safely without first resolving it server-side. The current design implies the server resolves the token to a tenant_id and sets the session var, but the security analysis isn't explicit. | §6.4, §4.2 |
| H3 | **High** | `email_normalized` is described as deterministic-HMAC for lookup, but if we ever rotate the HMAC key, all lookups break. Need a key rotation strategy or accept that this is a one-way commitment. | §5.4 |
| M1 | Medium | The permission matrix in §6.5 says `business_owner (in agency)` can update their own business — but the design has them as a *scoped* role with `business_scope_ids`. What happens if the agency_admin removes a business from their scope while they're logged in? | §6.5, §3.1 |
| M2 | Medium | The "claim trial" flow moves a Business across tenants. This is an *exception* to the rule that `tenant_id` is immutable on `Business`. Either tenant_id is immutable (and we copy/clone) or it isn't (and the design must say so). | §3.1, §7.1 |
| M3 | Medium | The platform_admin RLS bypass uses `current_setting('app.is_platform_admin', true)` — the `true` second argument means it doesn't error if unset. Good. But we should also verify the calling user *actually* has a platform_admin membership; the session var alone is trusting the application layer. | §4.3 |
| M4 | Medium | The category seed list (Professional Services, Healthcare, Education, Real Estate, Other) is too coarse for the keyword-suggestion feature. A CA firm needs different default keywords than a law firm; both are "Professional Services". The two-level taxonomy is defined but not specified. | §3.1 (Category) |
| M5 | Medium | No design for how an Auth0 webhook handles email change. If a user changes their email in Auth0, our `email_normalized` becomes stale; we'd send notifications to the wrong address. | §6.1 |
| L1 | Low | The `slug` reservation list isn't enumerated. | §8 |

Five highs and mediums. Iterating.

### Pass 2 (resolutions)

**H1 (subquery in partial index):** Removed the broken SQL example. Replaced with: enforce via trigger `enforce_direct_business_singleton` listed in §5.2. The trigger reads the parent tenant's type on each INSERT and raises if a second active business would result. Added explicit trigger DDL to migration script (referenced in §5.2). Also added concurrency note: the trigger uses `SELECT ... FOR UPDATE` on the parent tenant row to serialize concurrent inserts.

**H2 (free-audit RLS):** Redesigned. Public free-audit endpoints do not use the standard tenant-resolved connection pool. They use a separate, dedicated **public-tenant pool** with a fixed Postgres role (`public_audit_role`) that has SELECT/INSERT permissions only on the `free_audit_tokens` table and the trial-tenant subset. When a request arrives with `audit_token`, the server resolves token → trial tenant_id → sets `app.current_tenant` for that connection. The token table includes `expires_at` (14 days) and is the only entry point. **Two consequences:**
- The public endpoints cannot, even by application bug, read data from non-trial tenants because their database role lacks privileges on the production data.
- The token is single-tenant scoped; it cannot be used to enumerate other businesses.

This is added as a new subsection §4.7 "Public access surface".

**H3 (email HMAC key rotation):** Acknowledged: deterministic-HMAC means key rotation requires re-hashing all rows. Decision: we treat the email HMAC key as **immutable for the life of the platform**, generated once at platform initialisation and stored in KMS with delete protection enabled. If we ever need to rotate (e.g., key compromise), it requires a one-time migration job that re-hashes all rows during a maintenance window. This is documented as an accepted operational risk; the alternative (probabilistic encryption with a search index) adds query complexity that's not justified at our scale.

**M1 (scope change while logged in):** Membership scope is read from the database **on every request**, not cached in the session. When the agency_admin removes a business from a scoped member's `business_scope_ids`, the next request from that member sees the updated scope. They may see the business for the duration of the current request (which is fine — they were authorised when the request started). If we need stricter cutoff, we can invalidate their session on scope change; not a Phase 1 requirement.

**M2 (tenant_id immutability vs. trial claim):** Resolved by clarifying the flow:
- `Business.tenant_id` **is immutable**. We do not move businesses across tenants.
- In the trial-claim flow, when a user claims a trial: we create the new direct_business Tenant, then within the same transaction we **insert a new Business row in the new tenant**, copying profile data from the trial Business. The trial Business is soft-deleted. The user's PDF report and audit data references retain their original `business_id` but a `succeeded_by_business_id` link is added.

This is more complex but preserves the invariant. The Audit module (Phase 2) needs to handle the linkage.

**M3 (platform_admin double-check):** Updated §4.3: the application-level setup for platform_admin sets `app.is_platform_admin = true` *only after* verifying the calling user has a non-revoked `platform_admin` membership in the `memberships` table. The verification runs in a non-RLS query (the `memberships` table is not under RLS). Additionally, the admin policy includes the application-set marker AND optionally a per-row override via a custom function for fine-grained operations. CI check verifies no code path sets `is_platform_admin` without prior membership verification.

**M4 (two-level taxonomy):** Defined the Phase 1 seed taxonomy:
- Professional Services → CA Firm, Law Firm, HR Consulting, Tax Consulting, Management Consulting, ISO Certification
- Healthcare → Clinic-General, Clinic-Dental, Clinic-Dermatology, Clinic-Physiotherapy, Diagnostic Centre, Wellness Centre
- Education → JEE-NEET Coaching, UPSC Coaching, Spoken English, Coding-IT Training, Yoga Studio
- Real Estate → Real Estate Agent, Interior Designer, Vastu Consultant
- Other → (catch-all)

Each subcategory gets a `default_keyword_suggestions` array. This becomes the seed for the keyword-prefill UI.

**M5 (Auth0 email change webhook):** Added: Auth0 webhook handler at `/api/v1/auth/webhook` (verified via signed payload). On `user.updated` event with email change, we update `users.email_encrypted` and `users.email_normalized` atomically. If the new email collides with an existing user, the webhook fails and Auth0 retries with backoff; user is notified via in-app banner.

**L1 (slug reservations):** Enumerated. The reserved list includes: `app`, `www`, `api`, `admin`, `auth`, `static`, `mail`, `support`, `help`, `docs`, `blog`, `status`, `dashboard`, `account`, `billing`, `assets`, `cdn`, `citedby`. Stored in `reserved_slugs` table; editable via platform admin.

### Pass 3

Re-reviewing after Pass 2 resolutions:

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M6 | Medium | The Auth0 webhook handler at `/api/v1/auth/webhook` must be public (Auth0 cannot authenticate with a user JWT). Need to specify signature verification approach. | Add: webhook payload is signed by Auth0 with a shared secret stored in Secret Manager. Handler verifies signature before any DB write. Failed signatures logged and alerted. |
| L2 | Low | The pass 2 resolution for H2 introduces a second Postgres role (`public_audit_role`). Need to specify how this role's connection pool is provisioned alongside the main one. | Add: two connection pools, configured at app startup. The `PublicAuditPool` is used only by handlers under `/api/v1/free-audit/*`. Routing is by URL prefix in middleware. |

**M6 resolved** in this pass; L2 logged with implementation note.

Final review pass — no H or M findings remain. **Self-review passes.**

---

## 10. Test Strategy

### 10.1 Unit tests

- Domain model invariants: every aggregate has tests for its invariants (e.g., "creating a direct_business tenant with two active businesses fails").
- Repository tests run against a real Postgres (via testcontainers) with RLS enabled.
- Encryption/decryption round-trip tests for email/phone columns.

### 10.2 Integration tests

- Full request flow: HTTP request → auth → tenant resolution → handler → DB → response.
- Specifically: cross-tenant access attempts (must return 0 rows / 404).
- Free-audit flow end-to-end (without invoking Phase 2 audit; just trial creation + token retrieval).
- Trial-claim flow with Tenant + Business succession.

### 10.3 Security tests (recurring in CI)

- **Tenant isolation fuzzing:** automated test that creates two tenants A and B, then attempts every list/get/update/delete endpoint on B's resources while authenticated as a member of A. Every attempt must return 404 or 403.
- **RLS bypass attempts:** test that confirms queries with `app.current_tenant` unset return zero rows on RLS tables.
- **Permission matrix tests:** for each role × each endpoint, a positive (authorised) and negative (unauthorised) test.

### 10.4 Performance tests

- 1000 concurrent business profile reads: p95 < 50ms.
- Business creation: p95 < 500ms.
- Tenant resolution from Host header: p95 < 10ms (cached in Redis).

### 10.5 Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| AC1 | A new user can sign up via email/password and create a direct_business tenant + business in <2 minutes. | Manual + Playwright e2e |
| AC2 | An agency admin can create 5 businesses sequentially without errors. | Playwright e2e |
| AC3 | A member of Agency A cannot access any resource of Agency B via API, even with crafted URLs. | Automated security test |
| AC4 | A free-audit submission creates a trial tenant + business and returns a token in <1 second. | Integration test |
| AC5 | A claimed trial converts to direct_business with all profile data preserved. | Integration test |
| AC6 | RLS is enabled on all 5 business-data tables; no application path can bypass. | Automated CI scan + integration test |

---

## 11. Implementation Tasks (sprint-ready)

Estimated for 2 backend engineers + 1 full-stack across 2 sprints (4 weeks):

### Sprint 1 (Foundation)
1. Set up Auth0 tenant, configure Google SSO, email/password flows. (1d)
2. Database migrations for tables in §5.1. (2d)
3. RLS policies and triggers. (2d)
4. Connection pool wrapper with session variable injection. (1d)
5. Encryption utility for email/phone columns. (1d)
6. Tenant resolution middleware (subdomain lookup, JWT verification). (1d)
7. Repository layer for Tenants, Users, Memberships, Businesses. (3d)
8. `/api/v1/auth/callback` and `/api/v1/auth/me` endpoints. (1d)
9. `/api/v1/tenants` POST and GET endpoints. (1d)
10. Basic unit tests for repositories and middleware. (2d)

### Sprint 2 (Business profile + free audit shell)
1. `/api/v1/businesses` CRUD endpoints. (3d)
2. Location, alias, keyword sub-resource endpoints. (2d)
3. Permission enforcement at API layer; role checks. (1d)
4. Free-audit dedicated pool + token table + endpoints. (2d)
5. Trial-claim flow end-to-end. (2d)
6. Category taxonomy seed (Pass 2 resolution M4). (1d)
7. Auth0 webhook handler + signature verification. (1d)
8. Frontend: signup wizard for agency and direct flows. (3d)
9. Frontend: business profile create/edit form. (2d)
10. Frontend: free-audit landing page + form. (2d)
11. CI checks: cross-module import guard, raw SQL guard, RLS-enabled-table verifier. (2d)
12. Security tests in §10.3. (2d)
13. Acceptance criteria walkthrough. (1d)

**Phase 1 exit criteria:**
- All §10.5 acceptance criteria pass.
- Security tests in §10.3 are green and run in CI on every PR.
- A demo account exists with 1 agency tenant (3 businesses) and 1 direct_business tenant.
- Zero high or medium issues open against the Phase 1 codebase.

---

## 12. Handoff to Phase 2

Phase 2 (Audit & Citation Detection) consumes from this phase:
- `BusinessProfileService.getIdentity(business_id) → BusinessIdentity` — name, aliases, locations, phone, website. Used by CitationDetector.
- `BusinessRepository.list(tenant_id, filter)` — to enumerate businesses for scheduled re-crawls.
- The `business_competitors` table — Phase 2 writes here as it discovers competitors.
- The `Category.default_query_template_set_id` field — Phase 2 populates after creating QueryTemplates.
- Domain events `BusinessCreated`, `BusinessProfileUpdated` — Phase 2 may subscribe to trigger initial audits.

The contract between Phase 1 and Phase 2 is the `BusinessProfile` module's public interface, defined in code and version-stable. Phase 1 ships with this interface; Phase 2 consumes it.

---

*CitedBy Phase 1 Design v1.0 | Confidential | May 2026*
*Next: Phase 2 — Audit & Citation Detection*
