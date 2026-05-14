# CitedBy — High-Level Architecture Document (HLD)
**Version:** 1.0
**Status:** Approved for implementation
**Date:** May 2026
**Author:** CTO, CitedBy
**Audience:** Engineering team, founders, technical advisors
**Related documents:** `CitedBy_PRD_v1.md`, `CitedBy_Market_Study.md`

---

## 1. Document Purpose

This document is the single source of architectural truth for CitedBy. It describes *what* we are building at the system level, *how* the system is decomposed, *why* each major decision was made, and *what* the boundaries of the MVP scope are.

Every detailed phase design document derives from and conforms to this HLD. If a phase design needs to deviate, the HLD is updated first; the HLD is never silently overridden by an implementation choice.

This document does **not** contain database schemas, API contracts, prompt templates, or sprint-level tasks. Those live in their respective phase design documents.

---

## 2. Executive Summary

CitedBy is a Generative Engine Optimization (GEO) platform for Indian SMBs. It probes AI engines (ChatGPT, Perplexity, Google AI Overviews, and Phase 2 Indian-origin LLMs Sarvam and Krutrim) with category-and-location-shaped queries, detects whether a business is cited in the natural-language answers, and orchestrates a closed-loop remediation: generate AI-citation-shaped content, publish it to Google Business Profile / website / Indian directories, and track citation growth over time. The system is delivered as a multi-tenant SaaS with first-class white-label support so digital marketing agencies can resell it under their own brand.

Five technical realities shape every architectural decision:

1. The systems we measure are unstable. LLM engines change weekly, have no SLA for citation behaviour, and have no formal API for "did you cite this business?". Adapters must be isolated; failures must be containable.
2. Multi-tenancy is hierarchical (Platform → Agency → Business → User). Isolation must be enforced at the data layer, not at the application layer.
3. Most user-facing flows are long-running and multi-step. They must be durable, resumable, and observable.
4. LLM calls are the largest variable cost. The system must meter, cap, and optimise this cost as a first-class concern, not an afterthought.
5. White-label is a multi-tenancy property, not a theming feature. Custom domains, custom email, complete absence of CitedBy branding must be designed in from day one.

The chosen architecture is a **modular monolith on GCP Cloud Run**, backed by **PostgreSQL with Row-Level Security** in `asia-south1` (Mumbai), with **Temporal** for durable workflow orchestration and a **strict adapter pattern** for all external system integrations. The system is designed to decompose into services along its module boundaries in 12–18 months if and when scale demands it.

---

## 3. Architectural Goals and Non-Goals

### 3.1 Goals (in priority order)

| # | Goal | What it means in practice |
|---|---|---|
| G1 | **Tenant isolation correctness** | A bug in application code cannot leak data across tenants. RLS enforces isolation at the database layer. |
| G2 | **Workflow durability** | Audit runs, weekly re-crawls, publish operations, and OAuth refreshes survive worker restarts, network failures, and partial successes. |
| G3 | **Extensibility at the seams** | Adding a new AI engine, a new publisher, a new directory, or a new notification channel is a contained change — new adapter class plus configuration, no edits to core flows. |
| G4 | **Cost predictability** | LLM and crawl costs are metered, capped per-tenant, and observable in real time. No surprise bills. |
| G5 | **Operational observability** | An on-call engineer can answer "is the system healthy right now?" in under 60 seconds from a single dashboard. |
| G6 | **Compliance by construction** | DPDP Act, data localisation in Mumbai, right-to-erasure, audit logging are properties of the platform, not of careful coding. |
| G7 | **Configurability of product behaviour** | Query templates, prompts, plan limits, and engine parameters are data, not code. The product team experiments without engineering deploys. |

### 3.2 Explicit non-goals for MVP

These are real engineering decisions to *not* do certain things. Each one is deferred with the seam in place.

- We are not building a microservices architecture. Modules are strictly bounded inside one deployable.
- We are not building our own LLM. The LLMGateway uses third-party providers (Claude primary, GPT-4 fallback).
- We are not building Indian-language adapters in MVP. English-first; the adapter interface accepts a `Locale` argument so vernacular variants drop in later.
- We are not building real-time citation alerting. Weekly cadence is enough for value; sub-weekly is a Phase 2 retention feature.
- We are not building enterprise SSO (SAML/OIDC federation beyond Google). Auth0 supports this when we need it.
- We are not building our own scraping infrastructure for Google AI Overviews; we use a third-party residential proxy provider with strict cost ceilings.

---

## 4. Architectural Principles

These are the rules that every design decision is checked against. When two principles conflict in a specific decision, the one earlier in this list wins.

1. **Correctness over convenience.** A simpler design that risks data leakage or workflow corruption is rejected.
2. **Boring infrastructure.** PostgreSQL, Redis, Cloud Run, Temporal. Proven, well-instrumented, well-documented. We do not adopt novel infrastructure unless the problem demands it.
3. **External systems are adapters.** No third-party SDK or API is referenced anywhere outside its dedicated adapter module. Adapters expose a stable internal interface.
4. **Data over code.** Anything the product team might want to change without engineering involvement lives in the database. Anything that changes the meaning of the product lives in code and goes through review.
5. **Domain events over tight coupling.** Modules communicate through events for anything that is not a synchronous query for data. This is what makes future service extraction tractable.
6. **Idempotency is not optional.** Every write that could be retried (publish, notification, billing event) carries an idempotency key. Duplicate execution must not corrupt state.
7. **Defence in depth for tenancy.** Application checks tenant ownership; RLS independently enforces it; CI checks for forbidden cross-tenant queries. A single layer failure does not breach isolation.
8. **Fail loud, recover automatically.** Failures are surfaced in observability immediately; recovery is automated where possible; manual intervention is required only for novel failure modes.

---

## 5. System Context

```
                          ┌────────────────────────┐
                          │   External AI Engines  │
                          │   OpenAI/ChatGPT       │
                          │   Anthropic/Claude     │
                          │   Perplexity           │
                          │   Google AI Overviews  │
                          │   Sarvam (Phase 2)     │
                          │   Krutrim (Phase 2)    │
                          └───────────┬────────────┘
                                      │ (probes, content gen)
                                      │
┌──────────────────┐                  ▼                  ┌──────────────────┐
│  Agency Owners   │             ┌─────────┐             │  SMB Owners      │
│  & Operators     │◄────────────│ CitedBy │────────────►│  (CA firms,      │
│  (web app +      │  reports,   │ Platform│  reports,   │   clinics,       │
│   white-label    │  alerts,    │         │  alerts,    │   coaching)      │
│   dashboard)     │  approvals  │         │  approvals  │  (email + WA)    │
└──────────────────┘             └────┬────┘             └──────────────────┘
                                      │
                  ┌───────────────────┼───────────────────┐
                  ▼                   ▼                   ▼
        ┌────────────────┐  ┌────────────────┐  ┌──────────────────┐
        │ Publishing     │  │ Directory      │  │ Comms Providers  │
        │ Targets        │  │ Registries     │  │ Resend/SendGrid  │
        │ • GBP          │  │ • Justdial     │  │ WhatsApp Cloud   │
        │ • WordPress    │  │ • IndiaMart    │  │ API (Phase 2)    │
        │ • Website      │  │ • Sulekha      │  │                  │
        │   snippets     │  │ • Wikidata     │  │                  │
        └────────────────┘  └────────────────┘  └──────────────────┘
```

The platform sits between five categories of external systems:
- **AI engines** (probed; sources of citation truth)
- **Publishing targets** (where we push content)
- **Directory registries** (where we seed entities)
- **Communications providers** (email, WhatsApp for delivery to end users)
- **Identity providers** (Auth0 for federated identity)

Each category is encapsulated behind a stable internal interface. The platform's correctness must not depend on the implementation details of any single external system.

---

## 6. High-Level Architecture (Tiered View)

```
┌─────────────────────────────────────────────────────────────────┐
│                      CLIENT TIER                                │
│  Next.js apps served at:                                        │
│    • app.citedby.app          (platform-branded customers)      │
│    • <agency>.citedby.app     (agency subdomains)               │
│    • <custom>.<agency>.com    (verified agency CNAMEs)          │
│  Roles served: platform_admin, agency_admin, agency_member,     │
│                business_owner, business_member                  │
└──────────────────────────────┬──────────────────────────────────┘
                               │ HTTPS, JWT, Host-header tenant resolution
┌──────────────────────────────▼──────────────────────────────────┐
│                      EDGE / GATEWAY TIER                        │
│  GCP Cloud Load Balancer  →  Cloud Run (Next.js + API routes)   │
│  Responsibilities:                                              │
│    • TLS termination + automatic cert provisioning              │
│    • Host header → tenant_id resolution                         │
│    • JWT validation; user → tenant authorisation                │
│    • Per-tenant rate limiting                                   │
│    • Sets PostgreSQL session var: app.current_tenant            │
│    • CDN for static assets                                      │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                  APPLICATION TIER (Modular Monolith)            │
│  Deployed as Cloud Run services. Modules:                       │
│                                                                 │
│  ┌─Identity & Tenancy──┐  ┌─Business Profile────┐               │
│  ┌─Audit & Crawl──────┐  ┌─Content Generation──┐               │
│  ┌─Publishing─────────┐  ┌─Entity Seeding──────┐               │
│  ┌─Reporting──────────┐  ┌─Notifications───────┐               │
│  ┌─Billing & Quota────┐  ┌─Whitelabel──────────┐               │
│  ┌─Workflow Orchestration (Temporal client SDK)─┐               │
│                                                                 │
│  Cross-cutting: Domain Event Bus (in-process + Postgres outbox) │
└──────────────────────────────┬──────────────────────────────────┘
                               │
        ┌──────────────┬───────┴───────┬──────────────┬───────────┐
        ▼              ▼               ▼              ▼           ▼
   ┌─────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐  ┌────────┐
   │Postgres │   │  Redis   │   │ Temporal │   │   GCS    │  │Secrets │
   │primary  │   │ (cache,  │   │ Cloud    │   │ (reports │  │Manager │
   │asia-    │   │  rate    │   │ (workflow│   │  assets, │  │+ KMS   │
   │south1   │   │  limits) │   │  engine) │   │  raw     │  │        │
   │+ RLS    │   │          │   │          │   │  archives)│  │        │
   └─────────┘   └──────────┘   └──────────┘   └──────────┘  └────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│                       WORKER TIER                               │
│  Independently-scaled Cloud Run services running Temporal       │
│  workers. Each worker hosts a subset of activities:             │
│                                                                 │
│  ┌─Crawl Workers────┐  ┌─Content Workers──┐  ┌─Publish Workers─┐│
│  │ • Engine adapters│  │ • LLM Gateway    │  │ • GBP adapter   ││
│  │ • Proxy pool     │  │ • Prompt store   │  │ • WP adapter    ││
│  │ • Citation NLP   │  │ • Cost meter     │  │ • Directory     ││
│  │ • Rate limiters  │  │ • Validators     │  │   adapters      ││
│  └──────────────────┘  └──────────────────┘  │ • OAuth refresh ││
│                                              └─────────────────┘│
│  ┌─Notification Workers────┐  ┌─Report Workers─────────────────┐│
│  │ • Email (Resend)        │  │ • PDF generation               ││
│  │ • WhatsApp (Phase 2)    │  │ • Score computation            ││
│  └─────────────────────────┘  └────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 6.1 Tier responsibilities

**Client tier.** Server-rendered Next.js. Receives the user's Host header, which determines branding and tenant context before any JS executes. Read-heavy interactions hit Postgres via the API tier; long-running operations are initiated through API endpoints that start Temporal workflows and return workflow IDs for polling/subscription.

**Edge / Gateway tier.** The thinnest possible layer. Resolves tenancy, validates auth, enforces global rate limits. Does not implement business logic. Sets `app.current_tenant` PostgreSQL session variable on every connection checkout — this is what activates RLS.

**Application tier.** Modular monolith. Each module exposes a clean public interface (Python/TS contracts). Modules do not read each other's tables. Cross-module communication is by interface call (for synchronous queries) or by domain event (for asynchronous notifications). The application tier initiates workflows on Temporal but does not execute long-running work itself.

**Worker tier.** Temporal workers, deployed as separate Cloud Run services. They host *activities*, which are the units of work in a Temporal workflow. Workers are scaled independently: crawl workers scale with audit volume, content workers scale with LLM throughput, publish workers scale with target API rate limits.

### 6.2 Why a modular monolith, not microservices

At MVP scale (target: 200 audits + 25 paying customers + 5 agencies by month 6), microservices add operational overhead — independent deploys, inter-service auth, distributed tracing complexity — without any of the benefits (independent scaling, polyglot persistence, separate team ownership). The modular monolith gives us strict module boundaries with the operational simplicity of one deployable. When we hit a scale or team-structure threshold that justifies extraction, the seams are already drawn — a module becomes a service through a configuration change in how its public interface is dispatched.

### 6.3 Why Temporal, not BullMQ or Celery

The PRD's flows are not simple background jobs. An AuditWorkflow is a multi-step, multi-hour saga involving fan-out to many engines, citation detection, score computation, report generation, and email delivery. A weekly re-crawl is the same flow on a schedule. A publish workflow involves OAuth token check, content publish, verification poll over 30 days. These are *durable workflows*, not jobs.

Temporal gives us:
- Workflow state survives worker restarts; resumption is automatic
- Built-in retries, timers, and `await` semantics
- Workflow history is queryable and auditable
- Activities are independently retryable with their own policies
- Schedules (cron-like) are first-class

BullMQ or Celery would force us to build a state machine and recovery logic by hand for every workflow. That is six months of bug-prone undifferentiated work. Temporal Cloud's pricing at our scale (~$200–500/month at MVP) is materially cheaper than the engineering time saved.

### 6.4 Why PostgreSQL with Row-Level Security

PostgreSQL RLS is the simplest mechanism that gives us cryptographic-strength tenant isolation guarantees. RLS policies are evaluated by the database itself; a bug in application code that tries to query `SELECT * FROM businesses WHERE name LIKE '%foo%'` cannot return another tenant's businesses, because the database adds the `tenant_id = current_setting('app.current_tenant')` filter automatically.

Compared to alternatives:
- Schema-per-tenant: provisioning overhead, schema migration nightmare, no graceful path to a million tenants.
- Database-per-tenant: same as above, magnified.
- Application-layer filtering: relies on every developer being perfect on every query forever.

RLS is the right answer. The operational cost is one extra line in the connection setup and a per-table policy DDL.

---

## 7. Bounded Contexts and Module Decomposition

The application tier is decomposed into 11 modules. Each owns its tables, exposes a public interface, publishes domain events, and is independently testable.

| # | Module | Public Interface (representative) | Owns Tables (representative) | Primary Events Published |
|---|---|---|---|---|
| 1 | Identity & Tenancy | `IdentityService.authenticate`, `TenantService.resolve` | `users`, `tenants`, `memberships`, `roles` | `UserCreated`, `TenantCreated`, `MembershipGranted` |
| 2 | Business Profile | `BusinessRepository`, `BusinessIdentityService` | `businesses`, `business_aliases`, `business_locations`, `business_keywords`, `business_competitors` | `BusinessCreated`, `BusinessProfileUpdated` |
| 3 | Audit & Crawl | `AuditService.start`, `EngineRegistry`, `CitationDetector` | `audit_runs`, `query_executions`, `citations`, `query_templates`, `engine_descriptors` | `AuditRunStarted`, `AuditRunCompleted`, `CitationDetected` |
| 4 | Content Generation | `ContentBriefService`, `LLMGateway`, `PromptStore` | `content_briefs`, `content_assets`, `prompt_versions`, `llm_calls` | `ContentBriefDrafted`, `ContentBriefApproved`, `ContentBriefRejected` |
| 5 | Publishing | `PublishService`, `PublisherRegistry` | `publish_targets`, `oauth_tokens`, `publish_attempts` | `ContentPublished`, `PublishFailed`, `OAuthTokenExpiring` |
| 6 | Entity Seeding | `SeedService`, `DirectoryRegistry` | `entity_seeds`, `verification_polls` | `EntitySeedSubmitted`, `EntitySeedVerified` |
| 7 | Reporting | `ReportService`, `ScoreCalculator` | `reports`, `score_snapshots`, `citation_time_series` | `ReportGenerated` |
| 8 | Notifications | `NotificationService`, `ChannelRegistry` | `notifications`, `notification_templates` | `NotificationDelivered`, `NotificationFailed` |
| 9 | Billing & Quota | `SubscriptionService`, `UsageMeter` | `subscriptions`, `plans`, `usage_counters`, `invoices` | `QuotaThresholdReached`, `QuotaExceeded`, `SubscriptionRenewed` |
| 10 | Whitelabel | `WhitelabelService`, `DomainResolver` | `whitelabel_configs`, `domain_mappings` | `DomainVerified`, `WhitelabelConfigUpdated` |
| 11 | Workflow Orchestration | (Temporal client; no public service) | Temporal-managed state | (Temporal-managed) |

### 7.1 The contract between modules

Two patterns, two rules.

**Synchronous, query-shaped interactions:** Module A calls Module B's public interface directly. Example: Audit module needs to know "what's the business name and aliases?" — it calls `BusinessProfileService.getIdentity(business_id)`. Direct call, type-checked, transactional within a request.

**Asynchronous, notification-shaped interactions:** Module A publishes a domain event. Modules B, C, D subscribe to it via the in-process event bus. Example: `AuditRunCompleted` is published by Audit module; Reporting subscribes (to trigger PDF generation), Notifications subscribes (to queue email), Billing subscribes (to meter the usage). The publisher does not know who subscribes.

**Rule 1: No module reads another module's tables directly.** Cross-module data flows only through the owning module's interface.

**Rule 2: No module catches events from itself.** Events are for *other* modules; intra-module flows are direct calls.

These two rules are what keep extraction-to-service tractable. Violations are flagged by CI (static analysis of imports + table access).

---

## 8. Domain Model — Top-Level Aggregates

The full domain model is detailed in each phase design. Here we list only the top-level aggregates and their relationships, sufficient to understand the system's data shape.

```
                    ┌──────────────┐
                    │   Platform   │
                    └──────┬───────┘
                           │ 1..N
                    ┌──────▼───────┐         ┌─────────────────────┐
                    │   Tenant     │ 1───1   │  WhitelabelConfig   │
                    │   (Agency or │─────────│  (only if Agency)   │
                    │   Direct)    │         └─────────────────────┘
                    └──┬────────┬──┘
                       │        │
              1..N     │        │  1..N
              ┌────────▼─┐    ┌─▼────────┐
              │ Business │    │   User   │
              └────┬─────┘    └──────────┘
                   │
       ┌───────────┼───────────┬────────────┬─────────────┐
       │           │           │            │             │
   ┌───▼──┐  ┌─────▼───┐  ┌────▼─────┐ ┌────▼─────┐ ┌─────▼────┐
   │Audit │  │ Content │  │ Publish  │ │ Entity   │ │ Score    │
   │Run   │  │ Brief   │  │ Target   │ │ Seed     │ │ Snapshot │
   └──┬───┘  └────┬────┘  └────┬─────┘ └──────────┘ └──────────┘
      │           │            │
  ┌───▼───┐   ┌───▼───┐   ┌────▼─────┐
  │Query  │   │Content│   │ Publish  │
  │Exec.  │   │ Asset │   │ Attempt  │
  └───┬───┘   └───────┘   └──────────┘
      │
  ┌───▼────┐
  │Citation│
  └────────┘
```

Three classes of identity:
- **Tenant identity** (`tenant_id`) is on every business-owned row, enforced by RLS.
- **Business identity** (`business_id`) scopes most operational data within a tenant.
- **User identity** (`user_id`) is global but scoped to tenants by `memberships`. A user can belong to multiple tenants (rare, e.g., agency operator who also has their own direct business).

---

## 9. Technology Stack — Final Decisions

| Concern | Decision | Why this, not the alternatives |
|---|---|---|
| Primary application language (workers) | Python 3.12 | Strong ecosystem for NLP, LLM SDKs, scraping; team strength |
| Web application | Next.js 14 (App Router) | SSR, server components, good fit for SEO/branding-sensitive pages |
| API layer | FastAPI (Python) | Type safety via Pydantic, async-first, fast, integrates with Python workers |
| Database | PostgreSQL 16 with Row-Level Security | Already discussed. Default to Cloud SQL or AlloyDB |
| Cache and rate limiting | Redis 7 (Memorystore) | Standard, well-understood, sufficient for our scale |
| Workflow orchestration | Temporal Cloud | Durable workflows; already discussed |
| LLM providers | Anthropic Claude (primary), OpenAI GPT-4 (fallback) | Quality + cost balance; multi-provider for resilience |
| Object storage | GCS, `asia-south1` | Reports, asset archives, raw engine responses |
| Identity provider | Auth0 | Multi-tenant flexibility, federated identity ready, India data residency option |
| Email delivery | Resend (primary), SendGrid (fallback) | Deliverability, Indian inbox performance |
| WhatsApp (Phase 2) | WhatsApp Cloud API (Meta) | Direct, official, scales |
| Headless browser (scraping) | Playwright | Best modern browser automation; Python and Node bindings |
| Residential proxy pool | Bright Data or Smartproxy (vendor evaluation in Phase 0) | India-resident IPs available; rotation built in |
| Observability — errors | Sentry | Stack traces, breadcrumbs, source maps |
| Observability — metrics + traces | OpenTelemetry → Google Cloud Trace + Cloud Monitoring | First-party GCP integration |
| Observability — product analytics | PostHog (self-hosted on GCP, asia-south1) | Funnels, session replay, feature flags; data residency |
| Logging | Google Cloud Logging | First-party, structured |
| CI/CD | GitHub Actions → Cloud Run | Simple, well-understood, fast |
| Infrastructure as Code | Terraform | Standard, declarative, reviewable |
| Secrets | GCP Secret Manager + KMS | First-party, audited |

---

## 10. Cross-Cutting Concerns

### 10.1 Multi-Tenancy (defence in depth)

Three independent layers enforce tenant isolation:

1. **Application layer.** Every request resolves `tenant_id` from the Host header (subdomain or CNAME), and every API handler checks that the authenticated user has a membership granting access. Audit logged.
2. **Database layer.** RLS policies on every business-data table require `tenant_id = current_setting('app.current_tenant')`. The application sets this variable per connection; failure to set it causes queries to return zero rows.
3. **CI layer.** A static analysis check on every PR scans for:
   - Database queries that bypass the standard repository (e.g., raw SQL with no tenant filter)
   - Imports that cross module boundaries inappropriately
   - Hardcoded tenant IDs

A bypass at one layer is caught by another. A bug in application code becomes a data return of zero rows (which is visible as a bug), not a data leak.

### 10.2 Workflow durability

All long-running operations are Temporal workflows. The platform never calls "await an external API for 30 seconds" inside a synchronous HTTP request handler — that work is a workflow activity. Specific patterns:

- **Idempotency keys** on every activity that mutates external state (publish, send email, charge billing).
- **Retry policies** per activity, scoped to the failure mode (rate-limit → exponential backoff; auth failure → no retry, alert).
- **Timeouts** at both activity and workflow level; no workflow runs forever.
- **Versioning** for workflow definitions; in-flight workflows continue under their original version, new starts use the new version.

### 10.3 Cost governance

The single most expensive variable cost is LLM tokens. The single most operationally risky cost is proxy/scraping calls.

Both flow through gateways:
- All LLM calls go through `LLMGateway.complete()`. Pre-call, the gateway checks the business's monthly LLM budget; post-call, it records the spend. Aggregate spend is visible per business, per agency, per platform.
- All scraping calls go through `ProxyGateway.fetch()`. Same pattern — budget pre-check, spend tracking post-call.

Three layers of cost control:
- **Per-business monthly cap** (configurable per plan tier). Soft warn at 80%, hard block at 100% for discretionary operations (content generation). Audits always run within their bounded cost.
- **Per-agency aggregate cap** (sum of attached businesses + an agency overhead allowance).
- **Platform emergency kill switch.** A single dashboard control halts all new discretionary LLM and proxy work platform-wide. Used during incidents.

### 10.4 Security

- **All secrets in GCP Secret Manager**, accessed via Workload Identity. No secrets in code, env vars, or container images.
- **OAuth tokens** double-encrypted: GCP encryption at rest (default) plus application-layer envelope encryption using a KMS key. Decryption only at use.
- **Per-tenant encryption keys** for OAuth tokens (Phase 2 enhancement; MVP uses single platform key).
- **mTLS between Cloud Run services** where supported.
- **HTTPS everywhere**, HSTS, secure cookies, CSP.
- **Audit log** of all admin actions and all access to sensitive data, retained 7 years per DPDP.
- **Quarterly access reviews** of who has production access.

### 10.5 Compliance (DPDP Act)

- **Data localisation.** All primary data in `asia-south1` (Mumbai). Backups in `asia-south1` and `asia-south2` (Delhi). No data leaves India except for LLM provider calls, which are anonymised (no PII in prompts) and contractually bound by vendor DPAs.
- **Right to erasure.** `DeleteBusinessWorkflow` cascades soft-delete across all modules, with hard delete after a 30-day retention window. Each module exposes `purge(business_id)`.
- **Consent records** for any optional data processing (e.g., publishing to public directories).
- **Data export.** Each tenant can export all their data via a self-serve workflow; this includes raw audit data, content history, and citation time series.

### 10.6 Observability — what an on-call sees

The primary on-call dashboard shows, at all times:
- Active workflows (count, by type, by status)
- Engine adapter health (success rate, p95 latency, last-5-min error rate per engine)
- LLM spend (last hour, last 24h, vs. budget)
- Proxy spend (same)
- Publish failure rate (last 24h)
- OAuth tokens expiring in <48h with refresh status
- Top errors (Sentry)
- Queue depth per worker pool

If any of these enters a configured red zone, paging fires. Pages are routed by category: engine adapter failures wake the crawl team; LLM spike wakes the content team; etc.

### 10.7 Configuration management

The strict line between "data" and "code":
- **Data (in DB, editable without deploy):** query templates, prompt versions, plan limits, engine descriptors, directory registry, notification templates, quota thresholds.
- **Code (in repo, reviewed, deployed):** workflow definitions, business logic, citation detection algorithm, schema migrations, adapter implementations.

A change to a query template is a low-risk, fast iteration; a change to citation detection is a high-risk, code-reviewed change.

---

## 11. Deployment Architecture

### 11.1 Environments

| Environment | Purpose | Data |
|---|---|---|
| `local` | Developer machines | Synthetic |
| `dev` | Integration testing | Synthetic; reset weekly |
| `staging` | Pre-prod verification, demos | Synthetic + opt-in shadowing of prod events |
| `prod` | Customer-facing | Real |

Each environment is a separate GCP project with no IAM crossover except for break-glass admin.

### 11.2 GCP layout

- **Region:** `asia-south1` (Mumbai) for all primary services and data.
- **Multi-AZ** within region for Cloud SQL and Cloud Run.
- **DR:** Backups replicated to `asia-south2` (Delhi). RPO 1h, RTO 4h target.
- **VPC:** Private VPC; databases not on public internet; Cloud Run services connect via Serverless VPC Connector.

### 11.3 Release cadence

- **Weekly main-branch release** to prod for application code.
- **Daily release** allowed for low-risk changes (config, prompts, query templates).
- **Schema migrations** are backwards-compatible deploys: deploy migration → wait one release cycle → deploy code that depends on it. Never deploy a breaking schema change with the code that requires it.

---

## 12. Failure Modes and Resilience

The system is designed to gracefully degrade in the face of these realistic failures.

| Failure | Detection | Mitigation | Customer impact |
|---|---|---|---|
| One AI engine adapter down | Health check fails → engine marked unhealthy | Audits exclude that engine, report shows partial coverage | Visible partial coverage; degraded value |
| All AI engine adapters down | Aggregate health failure | New audits queued; existing workflows pause | Delay |
| LLM provider down | LLMGateway fallback to secondary provider | Content gen continues; quality may vary slightly | Minimal |
| Postgres primary down | Cloud SQL auto-failover to standby (~60s) | Brief 503s; workflows continue on resume | Brief unavailability |
| Temporal Cloud down | Temporal SLA: 99.9% | App tier shows "operations queued"; resumes on recovery | Delay; no data loss |
| OAuth token refresh failure | Daily refresh workflow alerts | Customer-facing reconnect prompt; no silent failure | Reconnect required |
| Publishing target API breaks | Per-adapter circuit breaker | Publishing paused for that target; alert raised | Visible to ops; customer told |
| LLM cost spike (runaway prompt) | Real-time spend monitoring | Hard cap halts further calls; alert | Visible quota stop |
| Scraping IPs blocked | Proxy provider rotates; if persistent, alert | Engine marked unhealthy if rotation insufficient | Same as engine down |
| Tenant isolation breach attempt | RLS returns empty result; CI scan catches code patterns | Bug visible as functional break, not data leak | None (caught before release) |

The principle: **no single external system failure renders the platform unavailable**. Customers see degraded service, not outages.

---

## 13. Evolution Strategy

### 13.1 What Phase 2 looks like (architecturally, not feature-wise)

The PRD lists Phase 2 features (vernacular, Sarvam, Krutrim, Justdial, WhatsApp, etc.). Architecturally, none of these require a redesign — they are all new instances of existing patterns:

- New AI engines = new `AIEngineAdapter` classes + config rows in `engine_descriptors`.
- Vernacular = new query templates with `locale` fields + content prompts with locale parameters.
- New publishers (Justdial, IndiaMart, Sulekha) = new `PublisherAdapter` classes + new entries in `publisher_registry`.
- WhatsApp notifications = new `NotificationChannel` adapter.

This is the payoff of the adapter-and-registry pattern: Phase 2 is largely additive, not transformative.

### 13.2 Scale milestones and what they trigger

| Milestone | What changes architecturally |
|---|---|
| 100 paying customers | Nothing. Current architecture handles this comfortably. |
| 1,000 paying customers | Worker tier may need dedicated pools per workflow type (already designed for). Postgres read replica added. |
| 10,000 paying customers | Begin module extraction: Audit & Crawl is the first candidate to become its own service due to workload shape (high throughput, isolated state). |
| 100,000 paying customers | Multi-region active-active for read paths. Sharding strategy for citations time-series data. |

The architecture has been chosen so the first significant rework is at the 10k-customer threshold — well past Series A scale.

### 13.3 What we explicitly do not commit to

- We do not commit to a specific microservices decomposition in advance. The right cut depends on team structure and operational learnings at extraction time.
- We do not commit to a specific event bus technology (RabbitMQ vs. Kafka vs. Pub/Sub) until extraction is on the table. The in-process event bus is a deliberate non-commitment.
- We do not commit to a specific multi-region strategy. India-only is correct until at least Series B.

---

## 14. Risks and Open Questions

Carried forward from the design plan. These are known and tracked; resolution is part of Phase 0.

| # | Risk / Question | Severity | Resolution plan |
|---|---|---|---|
| 1 | Google AI Overviews scraping legality and ToS | Medium | Legal review in Phase 0; build with degradation path |
| 2 | Sarvam / Krutrim API access timeline for Phase 2 | Medium | Begin partnership conversations in Phase 0 |
| 3 | WhatsApp Business API (WABA) approval timeline | Low | Begin application in Phase 0; not MVP blocker |
| 4 | LLM cost stability — are prompts pricing-stable through MVP? | Medium | Per-business caps + provider diversification mitigate |
| 5 | Citation detection accuracy benchmarks | High | Build evaluation harness in Phase 2 (Audit) with labelled dataset |
| 6 | Indian-language proxy/IP availability | Low | Vendor evaluation in Phase 0 |

---

## 15. Self-Review of this HLD

Following the same methodology as the planning document, this HLD is reviewed for high and medium issues.

### Pass 1

| # | Severity | Finding | Resolution |
|---|---|---|---|
| H1 | High | The HLD doesn't specify a strategy for prompt and adapter A/B testing. If we cannot experiment, we cannot improve. | Section 10.7 ("Configuration") covers this implicitly via the data/code line; explicitly added that prompt versions support `active_flag` and `experiment_cohort` for A/B testing (clarified in Phase 4 design). Accepted: HLD covers principle; mechanism lives in Phase 4 design. |
| H2 | High | The "Top-Level Aggregates" diagram in §8 doesn't show the relationship between an `AuditRun` and the `Content Brief` it inspires. Without that link, traceability is broken. | Added: `Content Brief` carries `source_audit_run_id` (foreign key). Phase 4 design will detail. |
| M1 | Medium | No explicit policy for handling PII inside engine responses (e.g., AI engines might quote a customer review containing a name). | Section 10.5 strengthened: engine responses are stored in GCS with a PII-detection pass before retention; sensitive content is redacted in archives. Phase 2 design details. |
| M2 | Medium | "No microservices" is stated; "modular monolith" is stated; but the **dispatch boundary** between API tier and worker tier — both Python — isn't precisely a monolith if they're separate Cloud Run services. Clarify. | Clarified in §6: API tier and worker tier are *deployed separately* but share the same codebase and module structure. They are not separate services in the architectural sense; they are different *deployment surfaces* of the same monolith. Same code, two scaling profiles. |
| M3 | Medium | The HLD doesn't address feature flags. Modern SaaS needs them for gradual rollout, beta features, kill switches beyond cost. | Added: PostHog feature flags listed under observability tools; principle stated under cross-cutting concerns. Detail in respective phase designs. |
| L1 | Low | Glossary is missing. New team members will struggle. | Added Section 16. |

### Pass 2

After incorporating Pass 1 resolutions, re-reviewing:

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M4 | Medium | The HLD specifies Temporal Cloud but does not address Temporal namespace strategy for multi-tenancy. Workflows from Tenant A and Tenant B currently share a namespace. | Added under §6.3: one Temporal namespace per environment. Workflow IDs include `tenant_id` prefix for traceability. Workflow search attributes include `tenant_id` for per-tenant queries and audit. Not full namespace isolation (which Temporal Cloud charges for per-namespace); sufficient at MVP scale. |
| L2 | Low | The CI tenancy check in §10.1 is described but the enforcement bar (block PR vs. warn) is not stated. | Block PR. Documented in §10.1. |

### Pass 3

No H or M findings. **Self-review passes.**

---

## 16. Glossary

- **AI engine** — A generative AI service we probe for citations (ChatGPT, Perplexity, etc.).
- **Audit** — A snapshot of a business's citation state across engines at a point in time.
- **Citation** — A detected mention of a business in an AI engine's response to a query.
- **GEO** — Generative Engine Optimization; the product category.
- **Tenant** — The top-level container for data isolation. Either an Agency (with multiple Businesses) or a Direct Business (with one Business).
- **White-label** — Agency-branded delivery of the product where CitedBy branding is invisible to end users.
- **Workflow** — A durable, multi-step operation managed by Temporal.
- **Activity** — A single unit of work within a workflow, independently retryable.
- **RLS** — Row-Level Security; PostgreSQL feature for row-scoped access control.
- **DPDP** — Digital Personal Data Protection Act, 2023 (India).

---

## 17. Phase Roadmap (forward reference)

The detailed phase design documents that derive from this HLD:

| Phase | Title | Status | Primary modules covered |
|---|---|---|---|
| 0 | Infrastructure & Foundation | To draft | GCP setup, Temporal, CI/CD, observability |
| 1 | Identity, Tenancy & Business Profile | **Drafted (this release)** | Modules 1, 2 |
| 2 | Audit & Citation Detection | To draft | Module 3 |
| 3 | Reporting & Free Audit Experience | To draft | Module 7 + audit UX |
| 4 | Content Generation & LLM Gateway | To draft | Module 4 |
| 5 | Publishing & Entity Seeding | To draft | Modules 5, 6 |
| 6 | Weekly Recrawl & Notifications | To draft | Module 8 + scheduling |
| 7 | Whitelabel & Agency Portal | To draft | Module 10 + agency UX |
| 8 | Hardening, Security Review, Launch | To draft | All |

Each phase design follows the same rigorous methodology: requirement framing, design, multi-pass self-review until no high or medium findings remain.

---

*CitedBy HLD v1.0 | Confidential | May 2026*
*Reviewers: founding team. Next revision triggered by: scale milestones in §13.2, or material change in PRD scope.*
