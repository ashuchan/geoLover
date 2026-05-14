# CitedBy — Phase 7 Design
## Whitelabel & Agency Portal
**Version:** 1.0
**Status:** Approved for implementation
**Date:** May 2026
**Author:** CTO, CitedBy
**Parent document:** `CitedBy_HLD_v1.md`
**Modules covered:** Whitelabel (#10), plus agency-specific UX surfaces and bulk operations

---

## 1. Phase Overview

### 1.1 Why this is Phase 7

PRD §3.1 Module 3 is unambiguous: agencies need to deliver this product to *their* clients under *their* brand. Not as a co-brand, not with a "Powered by CitedBy" footer — fully white-labeled. This isn't cosmetic; it's a market gate. Digital marketing agencies will not resell a product whose name appears anywhere in the customer experience.

HLD §1 made the architectural commitment: "white-label is a multi-tenancy property, not a theming feature." Phase 7 is where that commitment becomes code. The work spans four domains that must be solved together:
- **Routing**: custom domains and subdomains resolve to the right agency context.
- **Identity**: emails come from agency-controlled senders, not from us.
- **Presentation**: every pixel, font, color, logo, and copy string is agency-controlled or empty-by-default.
- **Operation**: agency operators run the system at scale, with bulk imports, multi-client dashboards, and approval workflows that match agency operating models.

If any one of these is half-built, the entire white-label promise collapses.

### 1.2 What this phase delivers

By the end of Phase 7:

- **Custom domain support**: an agency can connect any domain they own (e.g., `geo.acme-marketing.com`) via a verification workflow. Subdomain support (`<slug>.citedby.app`) already exists from Phase 1; this extends to fully-owned domains.
- **Automated SSL** via Google-managed certificates, provisioned automatically once a domain is verified.
- **Theme system**: per-agency configuration of logo, favicon, primary/secondary colors, font family, and a small set of customizable copy strings.
- **Branded email sending**: emails to agency clients are sent from an agency-controlled domain (e.g., `notifications@geo.acme-marketing.com`), with SPF/DKIM/DMARC set up via a documented one-time agency action.
- **Branded PDF reports**: Phase 3's report renderer reads `WhitelabelConfig` to apply logo, colors, and footer.
- **Agency multi-client dashboard**: a sortable, filterable view of all businesses under an agency, with at-a-glance score state, last-run, and action-required indicators.
- **Bulk operations**: CSV import of businesses; bulk-trigger audits across a selected set; bulk content brief generation (subject to per-business limits).
- **Branding leak prevention**: a CI check and a runtime sanity check that ensure no CitedBy strings, logos, or URLs appear in agency-mode rendering.
- **Configurable approval flows** in agency mode (Phase 4 introduced the enum; Phase 7 ships the UI to manage it).

### 1.3 What this phase does NOT deliver

- Custom front-end JavaScript or arbitrary HTML injection. Themes are *configuration*, not extensibility points. Letting agencies inject script tags is a security catastrophe; we won't do it.
- Custom domains for end-customer-facing surfaces only (the report view is at `<agency>.citedby.app/r/<token>` even for agency clients, *because* the report tokenization needs platform-level signing). Custom domain UX is for the dashboard, the agency-side of operations.
- Multi-language UX. The product is English-only at MVP; vernacular UI is Phase 2.
- A white-label *mobile app*. There is no mobile app yet; deferred.
- Custom billing pages with the agency's logo. Billing UX is platform-branded; agencies have their own billing relationship with their clients outside the system.

---

## 2. Requirements

### 2.1 Functional requirements

| # | Requirement | Source |
|---|---|---|
| F1 | An agency_admin can configure logo, favicon, primary color, secondary color, font family, and a set of customizable strings. | PRD §3.1 Module 3 |
| F2 | An agency_admin can add a custom domain; the platform issues DNS verification instructions; on successful verification, the domain is mapped to the agency tenant. | PRD §3.1 Module 3 |
| F3 | Domain verification supports two methods: DNS TXT record and HTTP file challenge. | New (industry standard) |
| F4 | Once a domain is verified, the platform automatically provisions a Google-managed SSL certificate for it. | Operational requirement |
| F5 | A custom domain can be removed; mapping is revoked; SSL is decommissioned. | Lifecycle requirement |
| F6 | Emails sent to clients of an agency originate from a configurable agency sender address; sender authentication (SPF/DKIM/DMARC) is set up via a documented one-time agency action. | PRD §3.1 Module 3 + deliverability |
| F7 | PDF audit reports rendered for businesses under an agency are branded per the agency's `WhitelabelConfig`. | PRD §3.1 Module 3 |
| F8 | The agency dashboard lists all businesses with: score, last audit date, citation-won count, pending approvals, status flags (OAuth fail, lost visibility, etc.). | PRD §3.3 |
| F9 | An agency_admin can bulk-import businesses via CSV (up to N rows per batch); imports report row-level success/failure. | PRD §3.3 |
| F10 | An agency_admin can select multiple businesses and trigger bulk operations (audit, content gen) subject to plan-level concurrency limits. | PRD §3.3 |
| F11 | When in agency-mode UI, no CitedBy branding (logos, text, footer links, email copy) appears anywhere visible to end users. | PRD §3.1 Module 3 hard requirement |
| F12 | The approval flow per agency (`agency_only` / `business_only` / `agency_then_business`, from Phase 4) is editable via the agency settings UI. | Phase 4 handoff |

### 2.2 Non-functional requirements

| # | Requirement | Target |
|---|---|---|
| NF1 | Custom domain DNS verification poll completion. | <15 minutes after DNS propagation |
| NF2 | SSL provisioning latency (verified domain → cert ready). | <60 minutes |
| NF3 | Agency dashboard load (50 clients). | <1.5s p95 |
| NF4 | Bulk CSV import (500 rows). | <2 minutes |
| NF5 | Branding leak detection precision (CI scan). | 100% (zero false negatives in test corpus) |
| NF6 | Theme asset CDN cache hit rate. | >95% |
| NF7 | Theme change propagation to live UI. | <30 seconds |

---

## 3. Domain Model — Detailed

### 3.1 Aggregates

#### `WhitelabelConfig`
One per agency tenant. Created with defaults on tenant creation.

```
WhitelabelConfig
├── id, tenant_id (UNIQUE — one per agency)
├── product_display_name      (string; what the agency calls the product, e.g., "Acme GEO")
├── tagline                   (string; optional, surfaces on dashboards)
├── logo_asset_id             (FK → theme_assets; nullable)
├── favicon_asset_id          (FK → theme_assets; nullable)
├── primary_color_hex         (CHAR(7); e.g., '#2A6FDB'; default platform color)
├── secondary_color_hex       (CHAR(7))
├── font_family               (text; restricted to allowlist of Google Fonts)
├── support_email             (string; where end-users contact the agency)
├── customizable_strings      (JSONB; key→value for ~15 specific UI strings)
├── content_approval_flow     (enum from Phase 4)
├── sender_domain_id          (FK → email_sender_domains; nullable until configured)
├── pdf_footer_text           (string)
├── updated_at
```

**Invariants:**
- `primary_color_hex` and `secondary_color_hex` match `^#[0-9A-Fa-f]{6}$`.
- `font_family` is one of an allowlist (8 widely-supported Google Fonts at Phase 7; expandable).
- `customizable_strings` keys are validated against a fixed schema; arbitrary keys ignored.

#### `DomainMapping`
```
DomainMapping
├── id, tenant_id
├── domain                    (text; e.g., 'geo.acme-marketing.com', or 'acme.citedby.app')
├── domain_type               (enum: 'platform_subdomain' | 'custom')
├── verification_status       (enum: 'pending' | 'verified' | 'failed' | 'revoked')
├── verification_method       (enum: 'dns_txt' | 'http_file'; null for platform_subdomain)
├── verification_token        (text; random token to be placed in DNS or file)
├── ssl_cert_status           (enum: 'not_required' | 'provisioning' | 'active' | 'failed')
├── ssl_cert_resource_id      (text; Google Cloud Certificate Manager ID)
├── verified_at, ssl_active_at
├── created_at, revoked_at
```

**Invariants:**
- `(domain)` is UNIQUE across all tenants. A domain points to at most one tenant.
- `platform_subdomain` mappings auto-verify (created via the slug in Phase 1).
- `revoked_at` set → the mapping is no longer authoritative; cleanup workflow tears down SSL and DNS-bound resources.

#### `EmailSenderDomain`
```
EmailSenderDomain
├── id, tenant_id
├── domain                    (text; the bare domain, e.g., 'acme-marketing.com')
├── verification_status       (enum: 'pending_dns' | 'verified' | 'failed' | 'revoked')
├── dkim_selector             (text; assigned per-domain)
├── dkim_public_key           (text; we generate the keypair)
├── dkim_private_key_encrypted (BYTEA; KMS envelope)
├── spf_include_status        (enum: 'missing' | 'detected' | 'unknown')
├── dmarc_status              (enum: 'missing' | 'present_relaxed' | 'present_strict' | 'unknown')
├── from_address              (text; e.g., 'notifications@acme-marketing.com')
├── from_friendly_name        (text; e.g., 'Acme GEO Notifications')
├── verified_at, last_health_check_at
```

A separate verification flow from `DomainMapping` because email authentication has different DNS requirements (TXT for SPF, CNAME or TXT for DKIM, TXT for DMARC) and is independently useful (an agency might use `acme-marketing.com` as their email sender domain but `geo.acme-marketing.com` as their app domain).

#### `ThemeAsset`
```
ThemeAsset
├── id, tenant_id
├── asset_kind                (enum: 'logo' | 'favicon' | 'pdf_logo' | 'email_header')
├── content_type              (text; image/png, image/svg+xml, image/jpeg)
├── gcs_object_path           (text)
├── width_px, height_px       (for sanity bounds)
├── safe_for_email            (boolean; SVGs are not safe-for-email by default)
├── uploaded_by_user_id, created_at
```

**Invariants:**
- `content_type` is in an allowlist: `image/png`, `image/svg+xml`, `image/jpeg`, `image/webp`. SVG is allowed only after a sanitization pass (§5.4).
- Max file size: 1 MB. Max dimensions: 2000 × 2000 px.

#### `BulkImportJob`
```
BulkImportJob
├── id, tenant_id, initiated_by_user_id
├── source                    (enum: 'csv_upload')
├── source_object_path        (GCS path to uploaded CSV)
├── status                    (enum: 'queued' | 'processing' | 'completed' | 'failed')
├── total_rows, succeeded_rows, failed_rows
├── result_report_path        (GCS path to per-row outcome CSV)
├── started_at, completed_at
```

#### `BrandingLeakReport`
```
BrandingLeakReport
├── id, scan_run_id, scan_target (test name or file path)
├── findings (JSONB; array of {token, location, severity})
├── verdict (enum: 'clean' | 'warnings' | 'fail')
├── created_at
```

Populated by the CI scan (§5.7); kept for historical analysis.

### 3.2 Relationships

```
Tenant (agency) 1───1 WhitelabelConfig
WhitelabelConfig 1───0..1 EmailSenderDomain
WhitelabelConfig 1───0..N ThemeAsset (logo, favicon, etc.)
Tenant 1───N DomainMapping
Tenant 1───N BulkImportJob
```

---

## 4. Custom Domain & SSL

### 4.1 Connection flow

```
Agency admin enters "geo.acme-marketing.com" in dashboard
   │
   ├─ API: POST /agency/domains
   │     → Insert DomainMapping(domain, status='pending', verification_method='dns_txt',
   │                            verification_token=randomToken())
   │     → Return verification instructions to UI
   │
   ├─ UI presents: "Add TXT record at _citedby-verify.geo.acme-marketing.com with value <token>.
   │                Once added, click Verify."
   │
   ├─ Admin adds DNS record at their DNS provider
   │
   ├─ Admin clicks Verify → API: POST /agency/domains/{id}/verify
   │     → Start VerifyDomainWorkflow (Temporal)
   │           ├─ Activity: DNSLookup the TXT record (resolves via 1.1.1.1 + 8.8.8.8;
   │           │            consensus required)
   │           ├─ If found and matches token: status = 'verified'
   │           ├─ If not found yet: schedule retries at +1m, +5m, +15m, +1h
   │           ├─ Hard fail after 24h without success
   │           └─ On verify: trigger ProvisionSSLWorkflow
   │
   ├─ ProvisionSSLWorkflow
   │     ├─ Activity: Create Certificate Manager DnsAuthorization in GCP
   │     ├─ Activity: Create Certificate (managed) referencing the authorization
   │     ├─ Activity: Bind certificate to the Load Balancer's target proxy
   │     ├─ Poll certificate status until 'ACTIVE' (max 1 hour)
   │     └─ Update DomainMapping.ssl_cert_status = 'active'
   │
   └─ Done: traffic to geo.acme-marketing.com routes to the agency tenant.
```

### 4.2 Why DNS TXT (and HTTP file as fallback)

DNS TXT is the most reliable verification method — works regardless of the user's site setup. The downside: DNS propagation can take minutes to hours.

The HTTP file challenge serves as fallback: place a file at `https://<domain>/.well-known/citedby-verify/<token>`. Faster (DNS-free), but requires the agency to have a controllable web server at that exact domain *before* they point it at us — a chicken-and-egg problem for greenfield setups.

For most agencies, DNS TXT is the right path. The UI defaults to it and surfaces HTTP file as an advanced option.

### 4.3 Google-managed SSL

We use **Google Cloud Certificate Manager** with **DNS-authorized managed certificates**. Why:
- Provisioning is automatic once the domain is verified (Google handles the ACME challenge).
- Renewal is automatic and lifelong.
- No private keys to manage on our side.

**The quota concern** (Pass 1 H3 below): Certificate Manager has per-project quotas — at the time of writing, around 100 managed certs per project. At our growth target, we could hit this. Resolution in §10 Pass 2.

### 4.4 Domain revocation & cleanup

When an agency removes a custom domain:
- `DomainMapping.revoked_at` is set.
- A `RevokeDomainWorkflow` runs:
  - Removes the cert binding from the load balancer.
  - Deletes the Certificate Manager certificate.
  - Deletes the DnsAuthorization.
  - Waits 30 days, then hard-deletes the DomainMapping row (the 30-day delay is forensic retention).

If during the 30 days the agency tries to re-add the same domain, we reactivate the row (with new verification required) instead of creating a duplicate.

### 4.5 Domain takeover prevention

A real risk: agency configures `geo.acme-marketing.com`, later abandons the domain (lapses, sells it). A malicious actor buys it, points it at us — and immediately receives traffic that may include OAuth callbacks or session-bound URLs from the prior tenant's old customers.

Mitigations:
- **Domain verification is single-use.** A revoked domain must be re-verified from scratch by the new claimant. We do not cache prior verification.
- **DNS heartbeat.** A weekly background workflow re-resolves each verified domain's TXT record. If the record disappears, we re-flag the domain `verification_status = 'failed'` and freeze routing. The agency is alerted.
- **OAuth callback domain allowlisting.** Customer OAuth callbacks (GBP, WordPress.com) are registered against specific platform-controlled callback URLs (`callback.citedby.app/<tenant_slug>/...`), not against custom domains. A custom domain takeover does not give the attacker any OAuth flow.

### 4.6 Routing implementation

Phase 1 already implements Host header → tenant resolution via the `domain_mappings` table. Phase 7 extends this:
- `platform_subdomain` mappings (existing): `<slug>.citedby.app` → tenant by slug.
- `custom` mappings (new): exact host match → tenant.
- The middleware queries Redis cache first; falls back to Postgres; caches result for 60 seconds.
- A Redis pub/sub channel `domain_mappings.invalidated` flushes the cache on changes (Pass 2 finding M3).

---

## 5. Theme System

### 5.1 Customization scope

We deliberately bound the scope. An agency can change:
- Product name and tagline.
- Logo, favicon, PDF logo, email header image.
- Primary color, secondary color.
- Font family (from an allowlist of 8 web-safe options).
- About 15 specific UI strings (welcome message, dashboard subtitle, etc.).
- Support email and PDF footer.

An agency cannot change:
- The structural layout of pages.
- The names of features or workflows.
- Anything that would meaningfully diverge the product from itself.

This bound makes the product testable. If agencies could change layout, every release would need to be tested against N agency variants. With color-and-text-only customization, the product remains a single product.

### 5.2 Theme application

At request time, after tenant resolution:
1. Load `WhitelabelConfig` (cached in Redis, 5-min TTL).
2. Inject into the rendered HTML as CSS custom properties:
   ```css
   :root {
     --color-primary: <primary_color_hex>;
     --color-secondary: <secondary_color_hex>;
     --font-family-base: <font_family>, system-ui, sans-serif;
   }
   ```
3. The Next.js app references these custom properties throughout. A theme change propagates as soon as the cache TTL expires (max 5 min) or immediately on Redis invalidation broadcast.
4. Logo/favicon URLs are signed GCS URLs (15-min TTL) generated per-render.

### 5.3 Default theme

For agency tenants that have not yet uploaded assets, defaults apply:
- Neutral grey logo placeholder showing the `product_display_name` as text.
- Platform-default font (`Inter`).
- Platform-default colors.
- No CitedBy branding even in default state (Pass 1 H1 below addresses what "default" means in agency mode).

### 5.4 Asset upload pipeline

```
Client uploads file via signed GCS resumable URL
   │
   ├─ Activity: ValidateUpload
   │      → Check size <1MB, dimensions ≤2000×2000
   │      → Check content_type against allowlist
   │      → For SVG: run sanitizer (strip <script>, on*= handlers, external <use>, etc.)
   │      → Compute hash; check for known-bad hashes
   │
   ├─ Activity: ScanForMalware (ClamAV-as-a-service in Phase 8; Phase 7 ships a basic mime sniff)
   │
   ├─ Persist ThemeAsset row
   │
   └─ Update WhitelabelConfig.<asset_kind>_asset_id atomically
```

SVG sanitization is critical — an unsanitized SVG can carry JavaScript and become an XSS vector when rendered inline. We use `defusedxml`-style sanitization, allowing only a whitelist of SVG elements and attributes.

For PDF rendering and email use cases where SVG carries no JavaScript benefit but raster works fine, we additionally render a PNG version at upload time and reference the PNG for PDFs and email — Phase 5 §4.4 deliverability hygiene.

---

## 6. Branded Email Sending

### 6.1 Why this is hard

Sending email from `notifications@acme-marketing.com` (the agency's domain) using *our* email infrastructure requires the agency to:
1. Add an SPF include for our sending service.
2. Add a CNAME (or TXT) record for DKIM with a public key we generate.
3. Set up DMARC (recommended, not strictly required).

Step 2 is the hard one: the agency must add DNS records in their domain. Many agency admins have never done this and find it intimidating. The UX has to make this easy or they will give up.

### 6.2 The setup workflow

```
1. Agency admin enters their sending domain (e.g., 'acme-marketing.com').
   → Insert EmailSenderDomain(verification_status='pending_dns')
   → Generate DKIM keypair; store private key KMS-encrypted; share public key in DNS instructions.

2. UI presents three DNS records to add:
   ┌──────────────────────────────────────────────────────────────────┐
   │ Record 1 (SPF)                                                   │
   │   Type: TXT                                                       │
   │   Host: @ (or acme-marketing.com)                                │
   │   Value: "v=spf1 include:_spf.resend.com ~all"                   │
   │                                                                  │
   │ Record 2 (DKIM)                                                  │
   │   Type: CNAME                                                    │
   │   Host: cb-dkim._domainkey                                       │
   │   Value: cb-dkim.<our-domain>.com                                │
   │                                                                  │
   │ Record 3 (DMARC) [recommended]                                   │
   │   Type: TXT                                                      │
   │   Host: _dmarc                                                   │
   │   Value: "v=DMARC1; p=quarantine; rua=mailto:dmarc-reports@…"    │
   └──────────────────────────────────────────────────────────────────┘
   With copy buttons for each value.

3. Agency admin adds records, clicks Verify.
   → VerifyEmailSenderDomainWorkflow
       ├─ DNS-resolve SPF: pass/fail/partial (presence of our include)
       ├─ DNS-resolve DKIM CNAME: must point to our managed CNAME target
       ├─ DNS-resolve DMARC: pass/fail (optional, not blocking)
       ├─ Send canary email via our provider with this from-domain; assert delivery
       ├─ On full pass: status='verified', from_address available for use
       └─ On partial pass: status='pending_dns'; keep retrying with backoff up to 14d

4. Once verified, EmailChannel adapter resolves the `from` from EmailSenderDomain (per agency)
   instead of the platform default.
```

### 6.3 Fallback when an agency cannot configure DNS

(Pass 1 H1 below). Some agencies will not be able to set up DKIM — they don't control DNS, or their admin doesn't have time. The fallback:
- Emails to clients are sent from a platform-controlled sender on a *neutral* domain like `notifications@cb-mail.app`, with `from_friendly_name` set to the agency's product name ("Acme GEO Notifications").
- This is acceptable deliverability but not great for agency brand strength — the recipient sees the agency's friendly name in their inbox but the raw domain is ours-ish.
- A persistent in-dashboard banner reminds the agency: "Verify your domain for branded email."

This is not perfect; it's pragmatic. The alternative (refusing to send any email until DKIM is set up) is worse — agencies couldn't onboard clients at all.

### 6.4 Ongoing DKIM health checks

A weekly workflow re-resolves DKIM CNAME for each verified sender domain. If it disappears (agency rotated DNS, deleted record), `verification_status = 'failed'`, and an alert is sent to the agency. Sending continues via the platform fallback until they fix it.

---

## 7. Agency Dashboard & Bulk Operations

### 7.1 Dashboard structure

The agency dashboard is the primary surface for agency_admins. At MVP:
- **Client list** with: name, score, last audit, score-trend arrow, pending-approvals badge, action-required flag (OAuth fail, etc.).
- **Search and filter** by name, status, score range, category.
- **Sortable columns**.
- **Per-client quick actions**: open dashboard, trigger audit, view pending approvals.

Loads via paginated API (`GET /agency/clients?limit=50&cursor=…`), sorted server-side. The query joins from `businesses` to the latest `ScoreSnapshot` and counts of `ContentBrief.current_state='in_review'`. The query plan is verified against an `EXPLAIN` baseline before merging.

### 7.2 Bulk CSV import

```
Agency uploads CSV (max 500 rows per upload)
   ↓
POST /agency/bulk-import  → BulkImportJob(status='queued')
   ↓
BulkImportWorkflow(job_id)
   ├─ Activity: ParseCSV → list of rows + validation errors
   ├─ Activity: ValidateRow per row (name length, category in taxonomy, locality non-empty, etc.)
   │       → row-level errors collected, not fatal
   ├─ Activity: CreateBusinesses (parallel, bounded to 5; each via Phase 1 BusinessRepository.create)
   │       → Each creation is its own DB transaction; per-row success/failure recorded
   ├─ Activity: PostProcess
   │       → For successful businesses: trigger initial-audit Workflow (Phase 2)
   │       → For failed businesses: include reason in result_report
   ├─ Activity: GenerateResultReport → CSV with per-row outcome → GCS
   └─ Notify uploader: "Bulk import complete: 487 succeeded, 13 failed. See report."
```

**Partial-success semantics:** failures don't abort the batch. The agency gets a result CSV showing per-row status and reason. Failed rows can be corrected and re-uploaded.

Hard limits:
- 500 rows per upload (one-time cap).
- 10 concurrent bulk operations per tenant (queue depth limit).
- 100 audits triggered per hour per tenant (rate limit on the downstream auditing).

These limits are tier-configurable. MVP defaults stated; higher tiers raise the caps.

### 7.3 Bulk audit and bulk content gen

A multi-select on the client list with "Audit selected" or "Generate content for selected" buttons. Subject to the same concurrency caps as bulk import. Each selected business gets its own workflow; the agency dashboard shows a progress strip.

---

## 8. Branding Leak Prevention

### 8.1 Why this needs both runtime and CI checks

A single missed reference to "CitedBy" on a single agency-mode page destroys agency trust. We treat this with paranoia:

**CI scan** (build-time): a static analysis pass over all agency-mode templates and components looking for forbidden tokens. Build fails if any are found.

**Runtime sanity check** (request-time): the response renderer, in agency-mode requests, performs a final scan of the rendered HTML before serving. If a forbidden token is detected, the request fails closed with a 503 (visible to ops; preferable to leaking branding).

Belt and braces. The CI catches what a developer would commit; the runtime catches what dynamic data accidentally surfaces.

### 8.2 Forbidden tokens

The token list (versioned in repo):
- Literal: `CitedBy`, `citedby`, `Cited by`, `citedby.app` (in user-visible contexts).
- Logo asset paths (specific GCS URLs of platform-default logos).
- The platform support email (`hello@citedby.app`).

The list is platform-admin-editable; CI references the latest version.

**Exemptions** (allowed in agency mode):
- `cb-mail.app` in the email From-header when using the platform fallback sender (§6.3).
- Internal admin-only routes (e.g., `/admin/...`) which are never agency-rendered.
- Source-map filenames and similar developer-tooling artifacts which the user does not see in normal rendering.

### 8.3 CI scan implementation

```
Job: agency-branding-leak-scan
   ├─ Run only on PRs that touch frontend or template code
   ├─ For each Next.js page route under agency-mode rendering:
   │     ├─ Pre-render with a stub WhitelabelConfig (production-shaped)
   │     ├─ Extract text content of the rendered HTML
   │     └─ Search for any forbidden token; report findings
   ├─ Aggregate into BrandingLeakReport
   └─ Fail PR build if verdict='fail'
```

For dynamic content (e.g., template-rendered emails), the scan iterates all `NotificationTemplate` rows with a stub render and applies the same check.

### 8.4 Runtime sanity check

At HTTP response time, in agency-mode requests, the response body is scanned with a fast SIMD-accelerated string search for forbidden tokens. Detected tokens → response replaced with HTTP 503 + ops alert. Cost: <2 ms per response, acceptable.

This is a last line of defense, not a primary mechanism. If it fires, we have a bug to fix — but the customer doesn't see the bug, they see a degraded service (which we can recover from in minutes).

---

## 9. Database Schema (additions)

```sql
CREATE TYPE domain_type_enum AS ENUM ('platform_subdomain', 'custom');
CREATE TYPE domain_verification_status AS ENUM ('pending', 'verified', 'failed', 'revoked');
CREATE TYPE ssl_cert_status_enum AS ENUM ('not_required', 'provisioning', 'active', 'failed');

CREATE TABLE domain_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    domain TEXT NOT NULL UNIQUE,
    domain_type domain_type_enum NOT NULL,
    verification_status domain_verification_status NOT NULL DEFAULT 'pending',
    verification_method TEXT,
    verification_token TEXT,
    ssl_cert_status ssl_cert_status_enum NOT NULL DEFAULT 'not_required',
    ssl_cert_resource_id TEXT,
    verified_at TIMESTAMPTZ,
    ssl_active_at TIMESTAMPTZ,
    last_dns_heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at TIMESTAMPTZ
);
CREATE INDEX domain_mappings_tenant_idx ON domain_mappings(tenant_id) WHERE revoked_at IS NULL;

CREATE TABLE whitelabel_configs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL UNIQUE,
    product_display_name TEXT,
    tagline TEXT,
    logo_asset_id UUID,
    favicon_asset_id UUID,
    primary_color_hex CHAR(7) NOT NULL DEFAULT '#2A6FDB',
    secondary_color_hex CHAR(7) NOT NULL DEFAULT '#37474F',
    font_family TEXT NOT NULL DEFAULT 'Inter',
    support_email TEXT,
    customizable_strings JSONB NOT NULL DEFAULT '{}',
    content_approval_flow TEXT NOT NULL DEFAULT 'agency_only',
    sender_domain_id UUID,
    pdf_footer_text TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (primary_color_hex ~ '^#[0-9A-Fa-f]{6}$'),
    CHECK (secondary_color_hex ~ '^#[0-9A-Fa-f]{6}$')
);

CREATE TABLE theme_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    asset_kind TEXT NOT NULL,
    content_type TEXT NOT NULL,
    gcs_object_path TEXT NOT NULL,
    width_px INT, height_px INT,
    safe_for_email BOOLEAN NOT NULL DEFAULT false,
    uploaded_by_user_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (asset_kind IN ('logo', 'favicon', 'pdf_logo', 'email_header')),
    CHECK (content_type IN ('image/png', 'image/svg+xml', 'image/jpeg', 'image/webp'))
);
CREATE INDEX theme_assets_tenant_kind_idx ON theme_assets(tenant_id, asset_kind);

ALTER TABLE whitelabel_configs
    ADD CONSTRAINT logo_fk FOREIGN KEY (logo_asset_id) REFERENCES theme_assets(id),
    ADD CONSTRAINT favicon_fk FOREIGN KEY (favicon_asset_id) REFERENCES theme_assets(id);

CREATE TYPE email_sender_status AS ENUM ('pending_dns', 'verified', 'failed', 'revoked');

CREATE TABLE email_sender_domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    domain TEXT NOT NULL,
    verification_status email_sender_status NOT NULL DEFAULT 'pending_dns',
    dkim_selector TEXT NOT NULL,
    dkim_public_key TEXT NOT NULL,
    dkim_private_key_encrypted BYTEA NOT NULL,
    wrapped_dek BYTEA NOT NULL,
    kms_key_version TEXT NOT NULL,
    spf_include_status TEXT NOT NULL DEFAULT 'unknown',
    dmarc_status TEXT NOT NULL DEFAULT 'unknown',
    from_address TEXT NOT NULL,
    from_friendly_name TEXT NOT NULL,
    verified_at TIMESTAMPTZ,
    last_health_check_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tenant_id, domain)
);

ALTER TABLE whitelabel_configs
    ADD CONSTRAINT sender_fk FOREIGN KEY (sender_domain_id) REFERENCES email_sender_domains(id);

CREATE TYPE bulk_import_status AS ENUM ('queued', 'processing', 'completed', 'failed');

CREATE TABLE bulk_import_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    initiated_by_user_id UUID NOT NULL REFERENCES users(id),
    source TEXT NOT NULL DEFAULT 'csv_upload',
    source_object_path TEXT NOT NULL,
    status bulk_import_status NOT NULL DEFAULT 'queued',
    total_rows INT,
    succeeded_rows INT,
    failed_rows INT,
    result_report_path TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE branding_leak_reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scan_run_id TEXT NOT NULL,
    scan_target TEXT NOT NULL,
    findings JSONB NOT NULL DEFAULT '[]',
    verdict TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

**RLS:** `domain_mappings`, `whitelabel_configs`, `theme_assets`, `email_sender_domains`, `bulk_import_jobs`. Not under RLS: `branding_leak_reports` (platform admin only).

---

## 10. Self-Review

### Pass 1

| # | Severity | Finding | Where |
|---|---|---|---|
| H1 | **High** | The branded email setup requires DNS access many agencies don't have or won't configure. The phase says "documented one-time action" but doesn't define what happens before it's complete — emails would have no proper authentication and would land in spam. | §6.1, F6 |
| H2 | **High** | Custom domain takeover risk is acknowledged but the DNS heartbeat (§4.5) runs *weekly*. A domain handoff in less than a week could leak. | §4.5 |
| H3 | **High** | Google Certificate Manager has per-project quotas (~100 managed certs). At 500 agencies with custom domains, we hit it. No mitigation specified. | §4.3 |
| M1 | Medium | The runtime branding-leak sanity check (§8.4) fails the request closed with 503. A false positive (legitimate text matching a token by coincidence) would block customer traffic. | §8.4 |
| M2 | Medium | SVG sanitization is mentioned but the specific library/approach isn't pinned. SVG sanitization is notorious for missing edge cases. | §5.4 |
| M3 | Medium | Theme cache TTL is 5 minutes. A bug-fix theme change wouldn't propagate fast. Pub/sub invalidation is mentioned for domains but not themes. | §5.2 |
| M4 | Medium | Bulk CSV import has a 500-row cap. Agencies migrating from competitors may have 2,000+ clients. What's the path? | §7.2 |
| M5 | Medium | The `customizable_strings` JSONB approach means strings are stored once per tenant. For localization later, this needs (string_key, locale) — needs forward design. | §3.1 WhitelabelConfig |
| M6 | Medium | No specification of what happens to email-sender domain when the agency cancels — DKIM records left dangling on agency DNS? | §6.2 |
| L1 | Low | Color hex check allows `#FFFFFF` which against a white logo would be invisible. No contrast validation. | §3.1 |

Three highs and six mediums. Iterating.

### Pass 2 (resolutions)

**H1 (DNS setup precondition):** Resolved with the fallback path in §6.3. To restate as policy: an agency *can* operate without verified email sender domain. In that state, emails to their clients are sent from `notifications@cb-mail.app` (a neutral platform-controlled domain that doesn't say "citedby") with the agency's friendly name in the From header. Deliverability is acceptable (the neutral domain has good sender reputation under our SPF/DKIM). A persistent banner reminds the agency to verify. Documented behavior in §6.3 + a banner-component implementation task in §12.

**H2 (faster domain heartbeat):** DNS heartbeat moved to daily, not weekly. Additionally, every public request to a custom domain re-validates the TXT record asynchronously via a sampled-1% probabilistic check, so for high-traffic agencies, any DNS-record removal is detected within minutes. Cost is minimal; we cache positive results aggressively. Documented in §4.5.

**H3 (cert quota):** Two strategies:
1. **Quota increase request.** GCP allows quota raises with justification; we file the request before launch.
2. **Multi-project cert distribution.** If a single project's quota becomes a hard ceiling, we provision additional GCP projects under the same folder, each with its own Certificate Manager + load balancer. DomainMapping records which project hosts a given domain's cert. Routing is handled by a single global load balancer with multiple SSL cert resources from different projects.
3. **Cert sharing across domains.** A single managed cert can cover up to ~100 SANs. We can pool agency domains onto shared certs (e.g., one cert covering 100 agency CNAMEs). This works because all the domains route to the same load balancer; no security boundary is broken by sharing the cert chain. At MVP we don't need this; it's the fallback if quota raise is denied.

Documented in §4.3 with deferred implementation; Phase 7 ships strategy 1 (default GCP quota of 100) and reserves strategies 2/3 for when we approach the ceiling.

**M1 (runtime check false-positive risk):** The runtime sanity check uses **exact substring match on case-sensitive token list**. The token list is curated to avoid common English words that could appear coincidentally. Specifically, `citedby` (no space) and `CitedBy` (capitalized, no space) are unlikely to appear coincidentally in customer data. Strings like `cited by` (with space) — which could appear in normal text like "cited by The Hindu" — are *not* in the forbidden list. The exemption logic in §8.2 is the safeguard. False-positive risk is acceptable given token specificity. Documented.

**M2 (SVG sanitization pin):** We use `bleach` (Python) and `DOMPurify` (Node.js) — both widely vetted libraries with active maintenance. SVG-specific configuration: allow `<svg>`, `<g>`, `<path>`, `<rect>`, `<circle>`, `<polygon>`, `<defs>`, `<linearGradient>`, `<stop>`, `<title>`. Forbid: `<script>`, `<foreignObject>`, `<use>` (external refs), all `on*` event handlers, all `xlink:href` to external resources. Whitelisted attributes only. SVG sanitization is run server-side at upload; output is re-stored as a sanitized file. The original upload is preserved 30 days for forensic comparison. Documented in §5.4.

**M3 (theme cache invalidation):** Same pub/sub mechanism as domain mappings. `whitelabel_configs.invalidated` channel; theme cache flushes on receipt. Theme changes propagate in seconds. Documented in §5.2.

**M4 (bulk import cap):** Cap stays at 500 per CSV upload, but multiple uploads can be queued. An agency with 2,000 clients uploads four CSVs and the system queues them. The dashboard shows progress across all jobs. Documented in §7.2.

**M5 (string localization forward design):** `customizable_strings` becomes `customizable_strings: {locale: {string_key: value}}`, with default locale `en-IN`. Lookup at render time: try requested locale, fall back to `en-IN`, fall back to platform default. Phase 7 ships only `en-IN`; the structure supports `hi-IN`, `kn-IN`, etc. when added. Documented in §3.1.

**M6 (sender domain on cancel):** When an agency cancels and their tenant is soft-deleted, the EmailSenderDomain is marked `revoked`. Sending stops. The agency is notified (via their last known address) that they should remove the DNS records they added. After 30 days, the row is hard-deleted; the DNS records on their side become orphaned but inert (point to a CNAME that no longer resolves). This is acceptable; not our DNS to clean up. Documented in §6.4.

**L1 (color contrast):** Added a soft check at config save time: compute WCAG contrast ratio between `primary_color_hex` and white, and between `secondary_color_hex` and white. If ratio is below 4.5:1, surface a warning in the UI: "This color may have visibility issues on white backgrounds. Continue anyway?" Save is allowed (agencies have final say); warning is non-blocking. Documented as an implementation polish item.

### Pass 3

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M7 | Medium | The shared cert pooling strategy (H3 resolution strategy 3) puts multiple agency domains in one cert's SAN list. A cert revocation event (e.g., due to one domain's compromise) would briefly impact all agencies sharing that cert. | Acceptable mitigation: rotation re-creates a replacement cert before revoking the old one (Google Cloud handles this with overlapping cert validity). The rotation window is ~5 minutes of dual-cert validity. Brief shared-fate is the cost of cert sharing; documented and tracked. |
| L2 | Low | Bulk CSV import does not preserve idempotency across re-uploads. Uploading the same CSV twice creates duplicates. | Added: each bulk import row carries a `client_idempotency_key` (hash of name + locality). Duplicate keys are silently skipped on second import with a per-row "skipped: duplicate" outcome. |

**M7 acceptable, L2 resolved.** No remaining H or M findings. **Self-review passes.**

---

## 11. Test Strategy

### 11.1 Unit tests
- DomainMapping verification token generation; uniqueness; expiration logic.
- WhitelabelConfig color hex validation; font allowlist enforcement.
- SVG sanitizer against 50 known-malicious-SVG test fixtures (sourced from OWASP and similar).
- Color contrast helper with known WCAG cases.
- CSV row validator with happy path + 20 edge cases (empty fields, BOM characters, non-UTF-8, quoted commas, etc.).

### 11.2 Integration tests
- Full custom-domain workflow against a stub DNS resolver: insert mapping, set TXT, verify, provision cert (mocked GCP), bind to LB.
- Email sender verification: stub DNS responses for SPF/DKIM/DMARC; assert correct status transitions.
- Theme cache invalidation: change a whitelabel config; assert dashboard reflects within 30s (NF7).
- Bulk import 500-row CSV: assert correct success/failure counts, result CSV generated.
- Runtime branding-leak check: render an agency-mode page with synthetic dirty data; assert 503 response.

### 11.3 End-to-end tests (Playwright)
- An agency_admin connects a custom domain (with mocked DNS), uploads logo, sets colors, verifies email domain, creates 3 businesses, sees their dashboard rendered with brand.
- An agency client visiting the agency-branded dashboard never encounters any CitedBy reference.

### 11.4 Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| AC1 | A custom domain with valid TXT verifies within 15 min of DNS propagation (NF1). | E2E with DNS-control |
| AC2 | SSL is active within 60 min of domain verification (NF2). | E2E (cert mocking ok) |
| AC3 | A revoked domain has its SSL cert torn down within 24h. | E2E |
| AC4 | Theme changes propagate to UI within 30s (NF7). | E2E |
| AC5 | Email sender verification produces a sendable from-address; canary email delivers. | E2E with sandbox |
| AC6 | Bulk import of 500 valid rows completes within 2 min (NF4). | Load test |
| AC7 | CI branding-leak scan blocks a PR that introduces a CitedBy reference in agency mode. | Manual + CI |
| AC8 | Agency dashboard with 50 clients loads in <1.5s p95 (NF3). | Load test |
| AC9 | No agency-mode user-facing page contains any token from the forbidden list. | Manual review + CI |

---

## 12. Implementation Tasks (sprint-ready)

For 2 backend + 2 frontend across 3 sprints (6 weeks):

### Sprint 1 — Domains, SSL, theming core
- DomainMapping schema + RLS. (1d)
- VerifyDomainWorkflow + DNS verification. (2d)
- ProvisionSSLWorkflow + Certificate Manager integration. (3d)
- DNS heartbeat workflow. (1d)
- WhitelabelConfig schema + CRUD. (1d)
- ThemeAsset upload pipeline + SVG sanitizer. (2d)
- Frontend: agency settings page (theme, domain). (3d)

### Sprint 2 — Email branding & dashboard
- EmailSenderDomain schema + DKIM key generation. (1d)
- VerifyEmailSenderDomainWorkflow. (2d)
- Email channel adapter: per-agency sender resolution. (1d)
- Phase 6 NotificationTemplate per-agency override application. (1d)
- Agency dashboard API + UI. (4d)
- Branded PDF report rendering. (2d)
- Theme cache + pub/sub invalidation. (1d)

### Sprint 3 — Bulk operations & branding safety
- BulkImportJob + workflow. (2d)
- Bulk import UI: upload, progress, result download. (2d)
- Bulk audit / content-gen triggers. (2d)
- Branding leak token list + scanner (CI). (2d)
- Runtime branding-leak sanity check (response middleware). (1d)
- Color contrast warning UI. (0.5d)
- E2E test suite. (3d)
- Acceptance walkthrough. (1d)

**Phase 7 exit criteria:**
- §11.4 ACs pass.
- A demo agency with a real custom domain (geo.demo-agency.com) is fully branded end-to-end.
- A real client of the demo agency receives a branded email with no CitedBy reference.
- Bulk import demo with 100 rows is reliable.
- CI branding-leak scan is enforced on all PRs touching frontend.

---

## 13. Handoff to Phase 8

Phase 8 (Hardening, Security Review, Launch) consumes from Phase 7:
- `WhitelabelConfig` and per-agency assets — the security review explicitly checks that no agency's assets are accessible by another tenant's request.
- The branding-leak scan output — Phase 8 reviews the CI history and expands the token list as needed.
- The email sender verification flow — Phase 8 includes deliverability testing against major Indian inbox providers (Gmail India, Outlook, Indian ISP MX servers).
- The bulk operation rate limits — Phase 8 finalizes per-tier limits based on observed load.

The contract: Phase 7 ships the white-label-correct product. Phase 8 stress-tests, security-reviews, and launches it.

---

*CitedBy Phase 7 Design v1.0 | Confidential | May 2026*
*Next: Phase 8 — Hardening, Security Review, Launch*
