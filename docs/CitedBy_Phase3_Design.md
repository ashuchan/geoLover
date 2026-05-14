# CitedBy — Phase 3 Design
## Reporting & Free Audit Experience
**Version:** 1.0
**Status:** Approved for implementation
**Date:** May 2026
**Author:** CTO, CitedBy
**Parent document:** `CitedBy_HLD_v1.md`
**Modules covered:** Reporting (#7) + the free-audit UX layer

---

## 1. Phase Overview

### 1.1 Why this phase, why now

Phase 2 produces correct audit data. Phase 3 makes it persuasive.

The PRD is explicit about the role of the free audit: it is the *single most powerful sales mechanism* the product has. The Pitch Playbook builds entire conversations around the moment a prospect sees the audit result. That moment is not Phase 2's job; it is Phase 3's.

Phase 3 is also where we close the funnel: the free audit user must, within 14 days, either convert to a paid customer or leave behind permission to follow up. The conversion mechanics — magic-link claim, plan selection, frictionless first paid audit — are built here.

### 1.2 What this phase delivers

By the end of Phase 3:

- A public landing page at `/audit` with a 60-second submission form (business name, locality, city, category, email, 5 keywords).
- A live progress UI that polls audit status and shows the user something is happening.
- An HTML report rendered at a token-scoped URL, visible to the submitter without login.
- A PDF version of the same report generated server-side, attached to the result email.
- An email delivery flow: instant "audit in progress" + completion email with PDF + 7-day follow-up.
- "Top 3 Quick Wins" generated via LLM from the audit data, gated by deterministic content validators.
- The claim flow: magic-link email → Auth0 signup → trial-to-direct_business conversion (handled by Phase 1; Phase 3 wires the UX).
- A "share report" link feature (read-only, expires after configured TTL).
- A report immutability + versioning model.
- A dashboard view of past audits for logged-in users (paid and trial-claimed).

### 1.3 What this phase does NOT deliver

- No paid plan billing enforcement (Phase 8).
- No agency-branded reports (Phase 7 white-label).
- No real-time citation alerting (Phase 6).
- No content publishing or generation (Phases 4, 5).
- No multi-language reports (post-MVP).
- No interactive report features beyond static + share link (e.g., drilldown filters are post-MVP).

---

## 2. Requirements

### 2.1 Functional requirements (traced from PRD §3.1 Module 1.3)

| # | Requirement | Source |
|---|---|---|
| F1 | A public submission form creates a trial business and starts an audit. | PRD §3.1 1.1 |
| F2 | The user receives an email confirming audit submission within 30s. | UX requirement |
| F3 | Report sections: AI Visibility Score, Citation Count per engine, Top Winning Queries, Lost Queries, Competitor Leaderboard, Top 3 Quick Wins. | PRD §3.1 1.3 |
| F4 | Top 3 Quick Wins are LLM-generated from the audit data, constrained to actionable items the product can deliver. | PRD §3.1 1.3 |
| F5 | A PDF version of the report is generated server-side. | PRD §3.1 1.3 |
| F6 | Completion email contains the PDF report and a link to the web version. | PRD §3.1 1.3 |
| F7 | The web report is accessible via the audit token (no login). | UX requirement |
| F8 | The audit token is valid for 14 days; report viewable indefinitely once claimed. | Phase 1 §3.1 |
| F9 | A "share report" feature generates a separate, expirable link the user can give to colleagues. | PRD §3.3 |
| F10 | An authenticated user has a dashboard listing all their audits, sortable by date and score. | PRD §3.1 1.1 |
| F11 | A claimed trial user can re-run an audit on the same business at any time. | UX requirement |
| F12 | Reports are immutable. Re-running an audit produces a new AuditRun and a new Report. | Phase 2 design |
| F13 | The free-audit form must support CAPTCHA and rate limiting (3/day/IP). | Anti-abuse |
| F14 | Audit run pages display partial completion clearly when applicable. | Phase 2 §7.5 |

### 2.2 Non-functional requirements

| # | Requirement | Target |
|---|---|---|
| NF1 | Audit submission to first email | <30s |
| NF2 | Audit completion to email with PDF | <10 min (PRD §3.1 1.3) |
| NF3 | PDF generation latency | <30s |
| NF4 | Web report page load p95 | <2s |
| NF5 | Quick Wins generation latency | <20s |
| NF6 | Quick Wins quality: human-rated relevance ≥85% on 100 reports | Manual eval |
| NF7 | Email deliverability (inbox rate, India) | ≥95% |
| NF8 | Free-audit fraud rate (audits on a business by someone unrelated to it) | <5% |

---

## 3. Domain Model

Phase 3 adds the following aggregates. All carry `tenant_id`.

### 3.1 `Report`
```
Report
├── id                         (UUID)
├── tenant_id, business_id     (denorm)
├── audit_run_id               (FK, immutable)
├── version                    (int; if report regenerated due to template change)
├── status                     (enum: 'generating' | 'ready' | 'failed')
├── score                      (snapshot of AuditRun.ai_visibility_score)
├── confidence_band            (snapshot)
├── completeness_pct           (snapshot)
├── pdf_gcs_uri                (string; nullable until ready)
├── pdf_byte_size              (int; nullable)
├── pdf_checksum               (sha256; for cache invalidation)
├── web_view_path              (string; canonical URL)
├── quick_wins                 (jsonb; structured list of QuickWin objects)
├── generated_at               (timestamptz; nullable until ready)
├── template_version           (string; report template version)
└── created_at
```

**Invariants:**
- A Report is immutable in its content once `status='ready'`. To "regenerate" we create a new Report with `version+1`.
- A Report's `audit_run_id` is immutable. The report views *that* AuditRun's data.

### 3.2 `QuickWin` (embedded in Report; structured for safety)
```
QuickWin
├── id                         (UUID; for tracking conversions)
├── title                      (string; ≤80 chars)
├── description                (string; ≤300 chars)
├── action_type                (enum from closed vocabulary; see §6)
├── target_query               (string; nullable; the specific lost query this addresses)
├── target_engine              (engine_key; nullable)
├── effort_estimate            (enum: 'quick' | 'medium' | 'longer')
└── confidence                 (float; LLM self-reported, scaled)
```

The `action_type` is a **closed vocabulary** of actions the product can actually deliver:
- `add_alias` — business has variant names not captured in profile
- `add_keyword` — add specific keyword to business profile
- `update_gbp_description` — improve Google Business Profile description with specific text
- `add_location_detail` — fill missing locality/address detail
- `generate_faq_content` — Phase 4 content generation can produce this
- `seed_directory` — Phase 5 entity seeding addresses this
- `clarify_service_offering` — write specific service blurb for profile

Quick Wins outside this vocabulary are rejected by the validator. This prevents the LLM from suggesting things like "buy more backlinks" or "rebrand your business" which we can't help with.

### 3.3 `ShareLink`
```
ShareLink
├── id                         (UUID)
├── tenant_id, business_id     (denorm)
├── report_id                  (FK)
├── token                      (random 32-char URL-safe string; indexed unique)
├── created_by_user_id         (FK; nullable for trial-claim auto-shares)
├── expires_at                 (timestamptz; default created_at + 30 days)
├── revoked_at                 (timestamptz, nullable)
├── view_count                 (int)
├── last_viewed_at             (timestamptz)
└── created_at
```

### 3.4 `FreeAuditToken` (Phase 1 introduced; Phase 3 owns the lifecycle)
The token table is owned by the Free Audit access path. It binds an anonymous user (by email + token) to a specific trial business and its first audit.

```
FreeAuditToken
├── id                         (UUID)
├── token                      (random 48-char; unique, indexed)
├── trial_tenant_id            (FK)
├── trial_business_id          (FK)
├── audit_run_id               (FK; the audit launched by this submission)
├── submitter_email_encrypted  (BYTEA)
├── submitter_email_normalized (TEXT; for dedup, expiry processing)
├── submitter_ip               (INET)
├── submitter_user_agent       (TEXT; truncated)
├── claim_attempted_at         (timestamptz, nullable)
├── claimed_at                 (timestamptz, nullable)
├── expires_at                 (timestamptz; default created_at + 14 days)
├── revoked_at                 (timestamptz, nullable)
└── created_at
```

---

## 4. The Free Audit Submission Flow

### 4.1 Pre-submission UX

A single-page form. Fields:
- Business name (required)
- City + locality (required; locality autocomplete based on city)
- Category dropdown (required; populated from `categories` taxonomy)
- Email (required; validated format)
- Up to 5 keywords (default suggestions appear based on category)
- Phone number (optional; for richer citation matching)
- Website (optional; same reason)

A reCAPTCHA v3 invisible challenge runs in background. Score < 0.5 → user is challenged with v2 visible. Score < 0.3 → submission rejected.

### 4.2 Submission handling

```
POST /api/v1/free-audit/start
    │
    ├── 1. Rate limit check (Redis): 3/day/IP, 5/day/email_normalized
    ├── 2. CAPTCHA verify (Google reCAPTCHA siteverify)
    ├── 3. Duplicate detection:
    │      Look up existing valid FreeAuditToken for (email_normalized, business_name_normalized, locality)
    │      → If found, return the existing token (idempotent)
    ├── 4. Begin transaction:
    │      a. Create Tenant(type='trial')
    │      b. Create Business(status='trial', source='free_audit')
    │      c. Create BusinessLocation (city, locality minimum)
    │      d. Create BusinessKeyword rows
    │      e. Create FreeAuditToken
    │      f. Start AuditWorkflow (Phase 2), get workflow_id
    │      g. Update FreeAuditToken with audit_run_id
    │      Commit.
    ├── 5. Trigger NotificationService: "audit in progress" email
    └── 6. Return { token, status_url, estimated_completion_at }
```

The transaction is intentionally tight — no LLM or engine calls inside it. External work happens after commit.

### 4.3 Progress polling

```
GET /api/v1/free-audit/{token}/status
```

Returns:
```json
{
  "status": "running",                  // pending | running | partial | completed | failed
  "progress": {
    "completeness_pct": 0.34,
    "engines_done": 1,
    "engines_total": 3,
    "queries_done": 17,
    "queries_total": 50
  },
  "report_ready": false,
  "estimated_completion_at": "...",
  "claim_offered": false               // becomes true after report ready
}
```

The frontend polls every 5s (with exponential backoff if the server returns a hint). Once `status=completed`, polling stops; the frontend redirects to the report view.

Backend-side, the polling endpoint reads from a cached projection of AuditRun + QueryExecution counts, refreshed every 10s. We do not run an aggregate count on every poll.

### 4.4 The "audit in progress" email

Sent within 30s of submission. Plain-text and HTML. Contents:
- Acknowledge submission
- Tell them they'll get a result within 10 minutes
- Include the status URL (token-scoped)
- Short note about what we're doing ("Querying ChatGPT, Perplexity and Google AI for queries like '{example_query}'")

---

## 5. Report Generation

### 5.1 The trigger

```
AuditRunCompleted event (from Phase 2)
        │
        ▼
ReportGenerationWorkflow.start(audit_run_id)
        │
        ├── 1. Load AuditRun + Citations + QueryExecutions + Business + Competitors
        ├── 2. Compute presentation aggregates (per-engine breakdown, query rankings)
        ├── 3. Generate Quick Wins (LLM call, validated)
        ├── 4. Render HTML report (server-side; Next.js render-to-string)
        ├── 5. Render PDF (headless Chrome via Puppeteer in a worker)
        ├── 6. Upload PDF to GCS
        ├── 7. Persist Report (status='ready', URIs, scores)
        ├── 8. Trigger NotificationService: completion email with PDF
        └── 9. Emit ReportGenerated event
```

Steps 4 and 5 are deliberately separate. The HTML report is the canonical view; the PDF is a rendering of the HTML (via `puppeteer.pdf()` after navigating to the rendered HTML URL). This way, the report has one source of truth.

### 5.2 Report sections — the layout

Section order (top to bottom):

1. **Hero**: Business name, locality, audit date. Big AI Visibility Score with confidence band annotation. Completeness pct if <100%.
2. **The Headline**: "[Business Name] was cited in N of M queries across X AI engines." If 0 citations: "Your business is invisible to AI engines for the queries that matter."
3. **By engine**: a grid showing per-engine citation count, comparison to competitors.
4. **Top winning queries** (up to 5): queries where this business was cited, with engine indicators.
5. **Lost queries** (up to 10): queries where the business was NOT cited but should have been, with which competitor was cited instead.
6. **Competitor leaderboard**: top 5 competitors by total citations, with the queries they're winning.
7. **Top 3 Quick Wins**: actionable recommendations.
8. **What's next**: a CTA — "Claim your audit and unlock weekly tracking + content generation."
9. **Methodology footer**: queries asked, engines covered, algorithm version, audit ID for reference.

Visually: clean, no jargon, every number explained. The report is the sales pitch.

### 5.3 The HTML rendering

Implemented as a Next.js server component route at `/r/{report_token}`. The route:
- Resolves token → Report → AuditRun → Business
- Renders with a fixed, premium-looking template
- Includes embedded SVG visualisations for score, per-engine breakdown, competitor comparison
- Mobile-responsive (most SMB owners view on mobile)

### 5.4 The PDF rendering

A separate worker activity (`render_pdf`):
- Navigates a headless Chrome instance to the rendered HTML report URL with a special header `X-PDF-Render: true` (causing the page to hide interactive elements, optimise for print).
- Calls `page.pdf({ format: 'A4', printBackground: true, ... })`.
- Uploads buffer to GCS with strong content addressing (filename = sha256).
- Returns GCS URI + size + checksum.

Why headless Chrome instead of a server-side PDF library: rendering quality. Charts, fonts, layout — all match the web exactly. The cost (a Chrome instance per render) is acceptable at MVP scale.

### 5.5 Report template versioning

The template version is recorded on every Report. If we make a template change (visual layout, sections), new audits get the new template; existing reports keep their template. A regeneration job can re-render a Report against the new template if explicitly requested.

---

## 6. Quick Wins Generation

The trickiest part of the report.

### 6.1 The LLM prompt — structure

```
System: You are a GEO recommendation engine. Given an audit of a business's AI citation
        performance, suggest 3 specific, actionable improvements. You MUST return JSON
        matching this schema: {schema_pasted_here}. Each suggestion's action_type MUST be
        one of: {closed_vocabulary}. Do not invent new action types. Do not suggest things
        outside this list, even if they would help.

User: Business profile:
        Name: {name}
        Category: {category}
        Locality: {locality}
        Current keywords: {keywords}
        
      Audit summary:
        Score: {score}/100, confidence: {band}
        Engines covered: {engines}, completeness: {pct}%
        
      Top 5 lost queries (queries where business not cited):
        1. "{q1}" — competitor cited: {comp1}
        2. ...
        
      Top 3 winning queries (where business cited):
        1. "{q1}" on {engines}
        
      Existing competitors: {comp_list}
      
      Suggest 3 Quick Wins. Be specific to this business and these lost queries.
```

### 6.2 Validation

The LLM output is parsed and validated against the schema. Specifically:
- `action_type` must be in the closed vocabulary
- `target_query` (if present) must match a lost query verbatim
- `target_engine` (if present) must match an engine_key from the audit
- `title` ≤ 80 chars, `description` ≤ 300 chars
- Description must not contain forbidden phrases (e.g., "buy backlinks", "pay for reviews", URLs)
- Must produce exactly 3 entries

If validation fails:
- Retry with a temperature reduction and a "your last output was invalid because X" preamble
- After 2 retry failures, fall back to a deterministic rule-based generator (described below) and log the LLM failure

### 6.3 The deterministic fallback

If LLM generation fails, we generate Quick Wins from rules:
- If `add_alias` not present in profile and the lost queries contain variant business name patterns → `add_alias` win
- If GBP description is missing or short → `update_gbp_description` win
- If no keywords cover a top lost query → `add_keyword` win
- And so on.

The deterministic generator is comprehensive enough that a report always has 3 wins. The LLM is preferred because the suggestions are more contextual; the fallback ensures we never ship an empty Quick Wins section.

### 6.4 Cost control

Quick Wins use the LLMGateway with a per-report budget (default ₹2 per Quick Wins generation, model=claude-haiku for cost). Total cost contribution per audit: small. The platform budget kill switch (HLD §10.3) applies.

---

## 7. The Claim Flow

### 7.1 Pre-claim state

The user has received their report. The web view and PDF both include a "Claim this audit and start tracking" CTA. Clicking it triggers:

```
POST /api/v1/free-audit/{token}/claim
    │
    ├── Validates token is unexpired and unclaimed
    ├── Triggers magic-link email via Auth0 passwordless flow
    └── Returns "email sent" confirmation
```

### 7.2 Magic-link return

User clicks the magic link → lands at `/claim/{auth0_continuation_token}`. The frontend:
- Completes Auth0 flow (account creation if new; login if existing)
- Calls `POST /api/v1/auth/callback`
- Backend identifies the pending claim, runs the Phase 1 trial-claim flow:
  - Create new Tenant (type=`direct_business`)
  - Copy Business profile from trial to new Tenant (Phase 1 §7.1)
  - Link trial Tenant via `claimed_from_trial`
  - Soft-delete trial Tenant + trial Business
  - The original Report and AuditRun retain their references (analytics-only links)
- Redirect to `<new_tenant_slug>.citedby.app/dashboard`

The user sees their audit on day one of being a customer. The continuity matters — the value is already proven.

### 7.3 Conversion telemetry

PostHog events:
- `free_audit_submitted`
- `free_audit_report_viewed`
- `free_audit_claim_clicked`
- `free_audit_magic_link_sent`
- `free_audit_claimed`

Funnel: `submitted → report_viewed → claim_clicked → claimed`. Drop-off at each step measured. The product team owns the conversion rate target.

---

## 8. Database Schema

Additions to Phases 1 and 2:

```sql
-- ========================
-- Reports
-- ========================

CREATE TYPE report_status AS ENUM ('generating', 'ready', 'failed');

CREATE TABLE reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL,
    audit_run_id UUID NOT NULL REFERENCES audit_runs(id),
    version INTEGER NOT NULL DEFAULT 1,
    status report_status NOT NULL DEFAULT 'generating',
    score REAL,
    confidence_band TEXT,
    completeness_pct REAL,
    pdf_gcs_uri TEXT,
    pdf_byte_size INTEGER,
    pdf_checksum TEXT,
    web_view_token TEXT NOT NULL UNIQUE,
    quick_wins JSONB,
    template_version TEXT NOT NULL,
    generated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (audit_run_id, version)
);
CREATE INDEX reports_business_idx ON reports(business_id, created_at DESC);
CREATE INDEX reports_audit_idx ON reports(audit_run_id);
CREATE INDEX reports_status_idx ON reports(status) WHERE status = 'generating';

-- ========================
-- Free audit tokens (introduced in Phase 1; owned by Phase 3 lifecycle)
-- ========================

CREATE TABLE free_audit_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token TEXT NOT NULL UNIQUE,
    trial_tenant_id UUID NOT NULL REFERENCES tenants(id),
    trial_business_id UUID NOT NULL REFERENCES businesses(id),
    audit_run_id UUID,
    submitter_email_encrypted BYTEA NOT NULL,
    submitter_email_normalized TEXT NOT NULL,
    submitter_ip INET,
    submitter_user_agent TEXT,
    claim_attempted_at TIMESTAMPTZ,
    claimed_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX free_audit_tokens_email_idx ON free_audit_tokens(submitter_email_normalized);
CREATE INDEX free_audit_tokens_expiry_idx ON free_audit_tokens(expires_at) WHERE claimed_at IS NULL;

-- ========================
-- Share links
-- ========================

CREATE TABLE share_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL,
    report_id UUID NOT NULL REFERENCES reports(id),
    token TEXT NOT NULL UNIQUE,
    created_by_user_id UUID REFERENCES users(id),
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    view_count INTEGER NOT NULL DEFAULT 0,
    last_viewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX share_links_report_idx ON share_links(report_id);
```

RLS applies to `reports` and `share_links`. `free_audit_tokens` is accessed only via the public-tenant pool (Phase 1 §4.7) and is not under RLS in the conventional sense.

---

## 9. API Surface

### 9.1 Public endpoints (free audit)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/free-audit/start` | Submit business, start audit (idempotent on dedup) |
| GET | `/api/v1/free-audit/{token}/status` | Poll audit status |
| GET | `/api/v1/free-audit/{token}/report` | Get report data (JSON) |
| GET | `/r/{web_view_token}` | Server-rendered HTML report (Next.js route) |
| GET | `/r/{web_view_token}/pdf` | Redirect to signed GCS URL for PDF |
| POST | `/api/v1/free-audit/{token}/claim` | Initiate claim |

### 9.2 Authenticated endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/v1/audits` | List audits for current business or tenant scope |
| GET | `/api/v1/audits/{id}` | Audit summary + report link |
| POST | `/api/v1/audits` | Start a new audit on a Business (authenticated) |
| GET | `/api/v1/reports/{id}` | Get report data (JSON) |
| POST | `/api/v1/reports/{id}/share` | Create a share link |
| DELETE | `/api/v1/share/{token}` | Revoke a share link |
| GET | `/share/{token}` | Server-rendered share view |

---

## 10. Self-Review

### Pass 1

| # | Severity | Finding | Where |
|---|---|---|---|
| H1 | **High** | The "Quick Wins" closed vocabulary is set early but several entries reference Phase 4 (`generate_faq_content`) and Phase 5 (`seed_directory`) capabilities. If those phases ship later, Quick Wins of those types are useless until then. We need to gate the vocabulary by what's currently shippable. | §3.2, §6.1 |
| H2 | **High** | The PDF rendering uses headless Chrome inside a worker. Each render spawns a browser instance. At 200 audits/day, that's 200 browser launches, which is heavy. Need warm-pool or browser-reuse strategy. | §5.4 |
| H3 | **High** | The web report at `/r/{token}` is publicly accessible by anyone with the token. The token is in the email. If the email is forwarded, the report is fully exposed including business contact info. Need to think about acceptable PII exposure for forwarded emails. | §5.3 |
| M1 | Medium | Magic-link claim: if the user types a different email at claim time than they used at submission, what happens? Different email → different account. Token binding is unclear. | §7.2 |
| M2 | Medium | The "audit in progress" email is sent within 30s. But the audit takes ~5 min. If the user opens the status URL immediately and the audit hasn't completed any queries yet, they see all zeros — looks like a broken product. | §4.4, §4.3 |
| M3 | Medium | The report carries the AuditRun's algorithm_version, but the report template version is separate. We have two versioning axes and no clear story for "what does version X of the report show for version Y of the algorithm." | §5.5 |
| M4 | Medium | Idempotency on submission is based on `(email_normalized, business_name_normalized, locality)`. But "name_normalized" doesn't yet account for trivial variations (Pvt. Ltd. vs. Private Limited). Same business resubmits → duplicate trial. | §4.2 |
| M5 | Medium | Share links can be revoked, but if a share link has been viewed (and cached in a recipient's browser), revocation may not take effect immediately. Need a "no cache" header policy on share pages. | §3.3 |
| L1 | Low | Quick Wins of type `seed_directory` rely on directory registry data from Phase 5. In Phase 3 we don't have that data; the LLM might suggest a directory we can't seed. | §6.1 |

Three highs and five mediums. Iterating.

### Pass 2 (resolutions)

**H1 (vocabulary gated by capability):** Resolved by making the closed vocabulary itself runtime-configurable from the `engine_descriptors`-style pattern. A new table `quick_win_action_types(action_type, display_name, capability_required, active)` is populated at Phase 3 launch with only Phase 1-3 capabilities active. Phase 4 launch adds `generate_faq_content` capability and activates that action type. Phase 5 launch activates `seed_directory`. The Quick Wins prompt is built from currently active action types only. New phases unlock new Quick Wins without code changes to Phase 3.

**H2 (PDF rendering at scale):** Resolved by maintaining a pool of warm Chromium instances. The PDF worker service runs N Chromium processes (N=3 at MVP) managed via `puppeteer-cluster` or similar pool library. PDF requests are queued and picked up by available browsers. A browser is recycled after every 100 PDFs (or 1 hour, whichever first) to bound memory. Cold start happens once per recycle, not per request. Throughput target: 60 PDFs/min per worker = 86K PDFs/day, vastly above MVP requirement. Resource impact: each Chromium ~200MB RAM; total worker memory ~1GB.

**H3 (PII in publicly-viewable report):** Acknowledged risk. Two mitigations:
1. The web report does not include the business's submitter email, phone number, or full address. It includes: business name, category, locality, city, and the audit data. These are *public-business* facts. A forwarded report exposes the same information a Google search exposes.
2. The PDF report adds a small "shared with you by [email]" watermark with the submitter's email (so the recipient understands the provenance). The submitter's email is *only* on the PDF, not the web view.
3. The web view has `noindex, nofollow` meta tags and `X-Robots-Tag: none` header so the URL isn't crawled.

Documented in §5.3 as the PII exposure policy.

**M1 (claim email mismatch):** Specified: at claim, the user must enter the same email used at submission. If they enter a different one, the claim is rejected with: "This audit was submitted with a different email. Please use [submitter@example.com] (or contact support if that's incorrect)." Auth0 magic-link is sent only to the submitter email. No flexibility — security over convenience for trial claim.

**M2 (early-poll empty state):** Resolved by frontend UX: until `completeness_pct >= 5%` OR `T+30s` has elapsed (whichever first), show a "warming up" indicator instead of the zero-citation rendering. After that, show actual partial state. This avoids the "looks broken" trap.

**M3 (versioning axes):** Clarified: the Report carries (a) `algorithm_version` from the AuditRun, and (b) its own `template_version`. Reports are rendered from a (template_version, audit data) pair. A regeneration with the same algorithm but new template is a new Report row (version+1) pointing to the same AuditRun. A redetection (new algorithm) is a new AuditRun and therefore a new Report. The customer-visible "report version" combines both.

**M4 (idempotency normalization):** The business-name normalisation is strengthened: lower-case, whitespace-collapse, diacritic-strip, strip common business suffixes (`pvt ltd`, `private limited`, `llp`, `inc`, `co`, `&`). A dedicated `normalise_business_name()` function in Phase 1 Business Profile module is the source of truth.

**M5 (share link revocation):** Two-part: (a) every share view returns `Cache-Control: private, no-cache, no-store`, `Pragma: no-cache`, and `X-Robots-Tag: none`. (b) The token-resolution endpoint checks revocation on every request (no Redis caching of revocation status — Postgres is the authority). Cost is one Postgres read per share view; share views are low-frequency.

**L1 (logged):** Quick Wins of type `seed_directory` are unlocked when the directory registry has at least 10 active entries. Operator-controlled. Acceptable to defer.

### Pass 3

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M6 | Medium | The PDF worker uses Chromium memory ~200MB × 3 instances = ~600MB. Cloud Run memory allocation must be sized to handle this. Default 512MB will OOM. | Specified: PDF worker Cloud Run service is sized to 2 vCPU + 2GB RAM. Documented in Phase 0 infra. |
| L2 | Low | The `noindex` headers (H3 resolution) need to apply to share views also. | Applied to all token-scoped report views: `/r/{token}`, `/share/{token}`. |

**M6 resolved** in this pass.

No remaining H or M findings. **Self-review passes.**

---

## 11. Test Strategy

### 11.1 Unit tests
- Quick Wins validator: every closed-vocabulary type accepted; every off-vocabulary type rejected.
- Quick Wins fallback generator: produces exactly 3 wins for any audit state.
- Report rendering: each section renders correctly given test AuditRun fixtures.
- Token generation: uniqueness, length, URL-safety, entropy.
- Idempotency normalization: business name suffix stripping, locale handling.

### 11.2 Integration tests
- Full free-audit submission → status polling → report viewing → claim → dashboard flow against testcontainers.
- PDF generation: render 10 audits in parallel, verify all PDFs are valid + checksums match cached values.
- Email delivery: against a mock Resend that captures payloads; verify content, links, headers.

### 11.3 End-to-end (Playwright)
- A user submits a free audit, sees "warming up", sees partial state, sees completed report.
- Claim flow: magic link → Auth0 → tenant created → dashboard.
- Share link: create, view, revoke, viewing fails after revoke.

### 11.4 Performance tests
- Web report page load against a real GCS-served audit: p95 < 2s.
- PDF generation throughput: 60 PDFs in 1 min on warm pool.
- Quick Wins generation: p95 < 20s including LLM call.

### 11.5 Quality tests
- Quick Wins relevance: a panel of 3 evaluators rates 100 production Quick Wins on (a) relevant, (b) actionable, (c) specific. Target: 85% rated "yes" on all three.

### 11.6 Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| AC1 | Submission to "audit in progress" email delivery: <30s. | Production monitoring |
| AC2 | Submission to completion email with PDF: <10 min p95. | Production monitoring |
| AC3 | A user can view their report without logging in via the token URL. | E2E test |
| AC4 | A claim flow completes in <3 minutes and creates a working direct_business tenant. | E2E + manual |
| AC5 | Quick Wins are constrained to the closed vocabulary; no off-vocabulary outputs in 100 production runs. | Audit log review |
| AC6 | PDF and HTML report visually match. | Manual visual diff |
| AC7 | Free-audit fraud rate (different submitter than business owner) measurable; controllable via CAPTCHA threshold tuning. | Production telemetry |

---

## 12. Implementation Tasks

Estimated: 1 backend + 1 full-stack + 1 designer × 3 sprints (6 weeks).

### Sprint 1 — Submission, Token, Workflow Trigger
- `/api/v1/free-audit/start` with rate limit + CAPTCHA + idempotency (3d)
- FreeAuditToken schema + trial-tenant creation transaction (1d)
- Phase 2 AuditWorkflow trigger wiring (1d)
- Status polling endpoint with cached projection (2d)
- Frontend: landing page + form + status page (4d)
- "Audit in progress" email template + delivery (1d)

### Sprint 2 — Reports + PDF
- Report schema + ReportGenerationWorkflow (2d)
- HTML report template (Next.js route, server-rendered) (4d)
- PDF worker service + warm browser pool (3d)
- Report token URL resolution + RLS-safe public view (1d)
- GCS upload + signed URL handling (1d)
- Completion email with PDF attachment (1d)
- ShareLink CRUD + share view (2d)

### Sprint 3 — Quick Wins, Claim, Dashboard
- Quick Wins LLM prompt + validator + closed vocabulary table (3d)
- Quick Wins deterministic fallback generator (2d)
- Claim flow: magic link → auth → trial-to-direct transition (3d)
- Authenticated audit list view (`/api/v1/audits`) (2d)
- User dashboard frontend showing audit history (3d)
- Telemetry events + funnel dashboard in PostHog (1d)
- Acceptance criteria verification (1d)

### Phase 3 exit criteria
- All §11.6 acceptance criteria pass.
- 50 real free audits run by team members across 5 cities; all produce sensible reports.
- Quick Wins quality panel completes 100-audit evaluation with ≥85% rated favourable.
- Funnel from `submitted` to `claimed` measurable; baseline conversion rate established.

---

## 13. Handoff to Phase 4

Phase 4 (Content Generation) consumes from this phase:
- Quick Wins of type `generate_faq_content`, `update_gbp_description`, `clarify_service_offering` become *executable* in Phase 4 — clicking one launches a content generation workflow.
- The Report becomes the *source* of content generation requests: each Quick Win carries the audit context that informs the generation prompt.
- The QuickWin closed vocabulary table is the integration point — Phase 4 activates new entries.

The contract between Phase 3 and Phase 4 is the `QuickWinExecuted` domain event (emitted when a user clicks "Apply" on a Quick Win) and the closed vocabulary registry.

---

*CitedBy Phase 3 Design v1.0 | Confidential | May 2026*
*Next: Phase 4 — Content Generation & LLM Gateway*
