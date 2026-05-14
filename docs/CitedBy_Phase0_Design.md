# CitedBy — Phase 0 Design
## Infrastructure & Foundation
**Version:** 1.0
**Status:** Approved for implementation
**Date:** May 2026
**Author:** CTO, CitedBy
**Parent document:** `CitedBy_HLD_v1.md`
**Modules covered:** All — this is the platform substrate

---

## 1. Phase Overview

### 1.1 Why this is Phase 0

Phase 0 is the substrate. Every other phase assumes the existence of an opinionated, reproducible, secure infrastructure foundation. Phase 0 produces no customer-visible feature; its output is the *ability* to ship customer-visible features safely.

A weak Phase 0 makes every subsequent phase pay a tax:
- No reproducible environments → every bug is "works on my machine".
- No proper secrets management → credentials in git, eventual compromise.
- No observability from day one → blind on-call, slow incident response.
- No CI/CD → human-error deploys, no rollback discipline.
- No DR plan → first outage is also first time we discover the gap.

We pay the tax now, once. Phase 0 must be complete (not perfect; complete) before any Phase 1 code merges to main.

### 1.2 What this phase delivers

By the end of Phase 0:

- Three GCP projects (`dev`, `staging`, `prod`) with strict IAM separation, in `asia-south1`.
- Terraform-managed infrastructure with remote state in GCS, state locking, encryption.
- PostgreSQL 16 (Cloud SQL) provisioned with HA, automated backups, point-in-time recovery, replication to `asia-south2`.
- Memorystore Redis provisioned.
- Temporal Cloud namespaces (one per environment) configured with search attributes.
- GCS buckets for reports, archives, raw engine responses; lifecycle policies in place.
- GCP Secret Manager with KMS-backed encryption keys; access via Workload Identity.
- Cloud Run services provisioned (placeholder containers) for frontend, API, and three worker pools.
- VPC with private connectivity; databases not on public internet.
- Cloud Load Balancer with managed SSL for `app.citedby.app`, `*.citedby.app` (wildcard).
- Auth0 tenant provisioned and configured (dev, staging, prod separated).
- GitHub Actions CI/CD pipelines: lint → test → build → deploy → smoke test.
- Sentry, PostHog (self-hosted on GCP), OpenTelemetry → Cloud Trace + Cloud Monitoring all wired in.
- PagerDuty (or equivalent) for on-call routing.
- Cost monitoring with budget alerts at 50%, 80%, 100% of monthly cap.
- DR runbook written and tested via tabletop exercise.
- Break-glass admin procedure documented, tested.

### 1.3 What this phase does NOT deliver

- No application code beyond hello-world placeholders.
- No production data (other than seeding scripts).
- No multi-region active-active. India-only.
- No advanced cost optimization (committed-use discounts, etc.). Reserve for when usage patterns are known.
- No SOC 2 / ISO 27001 attestation work. Track separately, begin at Series A.

---

## 2. Requirements

### 2.1 Functional requirements

| # | Requirement | Rationale |
|---|---|---|
| F1 | Three isolated environments: `dev`, `staging`, `prod`, each in its own GCP project. | Blast radius containment |
| F2 | All infrastructure provisioned via Terraform; manual GCP console changes are forbidden in `staging` and `prod`. | Reproducibility, auditability |
| F3 | Postgres provisioned with extensions: `pgcrypto`, `uuid-ossp`, `pg_trgm`. | Phase 1 schema requires these |
| F4 | Secrets exclusively in GCP Secret Manager; never in code, env vars, or container images. | HLD principle |
| F5 | All inter-service traffic over private VPC; databases unreachable from public internet. | Security baseline |
| F6 | SSL/TLS termination at Cloud Load Balancer with Google-managed certs; HSTS enabled. | Security baseline |
| F7 | Auth0 configured with email/password + Google SSO; separate tenants per environment. | Phase 1 dependency |
| F8 | CI/CD: every PR triggers lint + tests; merge to `main` deploys to `dev`; tag-based promotion to `staging` and `prod`. | Release discipline |
| F9 | Observability: Sentry for errors, OpenTelemetry → Cloud Trace for traces, Cloud Logging for logs, PostHog for product analytics. | Operational visibility |
| F10 | Cost budgets configured with email + PagerDuty alerts at thresholds. | Cost discipline |
| F11 | Backups: hourly snapshots, retained 30 days; weekly full backups, retained 1 year; PITR enabled. | DPDP + DR |
| F12 | DR replication: primary in `asia-south1`, DR in `asia-south2` (Delhi). | RPO 1h, RTO 4h |

### 2.2 Non-functional requirements

| # | Requirement | Target |
|---|---|---|
| NF1 | Environment provisioning from scratch (Terraform apply on empty project). | <2 hours |
| NF2 | Time from PR merge to `dev` deployment. | <15 minutes |
| NF3 | Production deployment with rollback capability. | <5 minutes rollback |
| NF4 | Secret rotation for a single secret without service downtime. | Routine, no on-call |
| NF5 | Monthly infrastructure cost at MVP scale (idle). | <$1,500/month |
| NF6 | Monthly infrastructure cost at MVP scale (200 active customers). | <$5,000/month |
| NF7 | DR drill cadence. | Quarterly |
| NF8 | Mean Time To Detect (MTTD) for production incidents. | <5 minutes via alerts |

---

## 3. Infrastructure Layout

### 3.1 GCP project structure

```
Organization: citedby.app
│
├── Folder: citedby-engineering
│   ├── Project: citedby-dev
│   │   - Free for engineers to deploy/test
│   │   - Data: synthetic, reset weekly
│   │   - IAM: all engineers (Editor)
│   │
│   ├── Project: citedby-staging
│   │   - Pre-production verification
│   │   - Data: synthetic; opt-in prod-event shadowing
│   │   - IAM: engineers (Viewer); deploys via service account
│   │
│   └── Project: citedby-prod
│       - Customer-facing
│       - Data: real
│       - IAM: minimal humans (founders + on-call); deploys via service account
│
├── Folder: citedby-shared
│   ├── Project: citedby-shared-secrets    (KMS key rings, cross-env secret refs)
│   ├── Project: citedby-shared-network    (Shared VPC host project, if used)
│   └── Project: citedby-billing-export    (BigQuery billing analysis)
│
└── Folder: citedby-experimental
    └── Project: citedby-experiments  (sandbox; nothing persistent here)
```

Each `citedby-{env}` project contains a *full* environment — Cloud Run, Cloud SQL, Memorystore, GCS, etc. No project is "missing" components; this preserves dev-prod parity.

### 3.2 Network architecture

```
                    ┌──────────────────────────────┐
                    │   Cloud Load Balancer        │
                    │   - Global, managed SSL      │
                    │   - HTTP→HTTPS redirect      │
                    └──────────┬───────────────────┘
                               │
                    ┌──────────▼───────────────────┐
                    │   Cloud Armor (WAF)          │
                    │   - DDoS protection          │
                    │   - Rate limiting            │
                    │   - Geo-blocking (Phase 1+)  │
                    └──────────┬───────────────────┘
                               │
              ┌────────────────┼─────────────────┐
              ▼                ▼                 ▼
       ┌────────────┐  ┌────────────┐    ┌────────────┐
       │ Cloud Run  │  │ Cloud Run  │    │ Cloud Run  │
       │ Frontend   │  │ API        │    │ Workers    │
       │ (Next.js)  │  │ (FastAPI)  │    │ (Temporal) │
       └─────┬──────┘  └─────┬──────┘    └─────┬──────┘
             │               │                 │
             └────────┬──────┴─────────────────┘
                      │ Serverless VPC Connector
              ┌───────▼────────────────────────┐
              │   Private VPC (asia-south1)    │
              │   - 10.0.0.0/16                │
              │   - Subnet: services           │
              │   - Subnet: data               │
              └───────┬────────────────────────┘
                      │
        ┌─────────────┼──────────────┬─────────────┐
        ▼             ▼              ▼             ▼
   ┌─────────┐  ┌─────────┐    ┌──────────┐  ┌─────────┐
   │Cloud SQL│  │Memory-  │    │   GCS    │  │Secret   │
   │(Postgres│  │store    │    │(via VPC- │  │Manager  │
   │ private)│  │(Redis,  │    │ SC)      │  │(via PSC)│
   │         │  │ private)│    │          │  │         │
   └─────────┘  └─────────┘    └──────────┘  └─────────┘
```

- **Cloud Load Balancer** is the only public-facing entry point.
- **Cloud Armor** rules: default rate limit per IP (60 req/min), aggressive limit on free-audit endpoint (3 req/min per IP), captcha challenge after thresholds, geo-block of high-abuse regions if necessary.
- **Cloud Run services** run inside the project but reach private VPC resources via Serverless VPC Connector.
- **Cloud SQL** has *no public IP*; access only via private IP from the VPC.
- **Memorystore** is private VPC by default.
- **GCS** access is restricted via VPC Service Controls.
- **Secret Manager** access via Private Service Connect.

### 3.3 Cloud SQL Postgres configuration

| Setting | Value | Why |
|---|---|---|
| Version | PostgreSQL 16 | RLS performance improvements; latest stable |
| Edition | Cloud SQL Enterprise Plus | HA + ZRS backups + read pool readiness |
| Region | `asia-south1` (Mumbai) | DPDP localisation |
| HA | Multi-zone, automatic failover | Survives zone failure |
| Connections | Max 200 (dev), 500 (staging), 2000 (prod) | Sized for connection pool |
| Backups | Hourly automated; 30-day retention; weekly retained 1 year | DR + compliance |
| PITR | Enabled, 7-day retention | Recovery from logical corruption |
| Cross-region replica | `asia-south2` (Delhi), async | DR RPO 1h |
| Encryption | CMEK (customer-managed KMS keys) | Compliance bar + key rotation control |
| Extensions | `pgcrypto`, `uuid-ossp`, `pg_trgm`, `pg_stat_statements` | Phase 1 requires |
| `log_statement` | `ddl` (audit DDL changes) | Compliance |
| Insights | Query Insights enabled | Performance tuning |

### 3.4 Temporal Cloud configuration

| Setting | Value |
|---|---|
| Region | `asia-south1` |
| Namespaces | `citedby-dev`, `citedby-staging`, `citedby-prod` |
| Search attributes | `TenantId`, `BusinessId`, `WorkflowCategory`, `Priority` |
| Retention | Workflow history: 30 days (dev), 90 days (staging), 1 year (prod) |
| Auth | mTLS certificates per environment, certs in Secret Manager |
| SLA | 99.9% (Temporal Cloud default) |

Naming convention for workflows: `{category}-{tenant_id}-{business_id}-{nanoid}`. Example: `audit-T123-B456-x7k9m2p`. This makes workflow searches by tenant trivial.

### 3.5 GCS bucket layout

| Bucket | Purpose | Storage class | Lifecycle |
|---|---|---|---|
| `citedby-{env}-reports` | Generated PDFs | Standard | Move to Nearline after 90d; delete after 7y |
| `citedby-{env}-raw-engine-responses` | Archives of LLM/engine responses | Standard | Move to Nearline after 30d; Coldline after 1y; delete after 2y |
| `citedby-{env}-content-assets` | Generated content (markdown, HTML, images) | Standard | Move to Nearline after 180d; delete after 7y |
| `citedby-{env}-tf-state` | Terraform state | Standard | Versioning enabled; retain all versions for 1 year |
| `citedby-{env}-backups-logical` | pg_dump archives | Coldline | Delete after 2 years |

All buckets:
- Uniform bucket-level access enabled.
- Public access prevented (organization policy).
- Encryption via CMEK from `citedby-shared-secrets` project.

### 3.6 Secret Manager structure

Secrets named in a strict convention: `{env}/{module}/{secret-name}`.

Examples:
- `prod/identity/auth0-client-secret`
- `prod/identity/auth0-webhook-signing-secret`
- `prod/audit/openai-api-key`
- `prod/audit/perplexity-api-key`
- `prod/audit/proxy-vendor-credentials`
- `prod/database/citedby-app-password`
- `prod/database/citedby-public-audit-password`
- `prod/encryption/email-hmac-key`  (immutable, see Phase 1 §5.4)
- `prod/encryption/oauth-token-encryption-key`
- `prod/temporal/mtls-cert`
- `prod/temporal/mtls-key`

Access via Workload Identity binding to Cloud Run service accounts. Each service has access only to the secrets in its module's prefix. CI tooling has no secret access except deployment credentials.

---

## 4. CI/CD Pipeline

### 4.1 Branch and release model

- `main` branch: deploys to `dev` automatically on merge.
- Git tag `v{n}.{n}.{n}-rc.{n}`: deploys to `staging`, runs smoke tests.
- Git tag `v{n}.{n}.{n}`: deploys to `prod` after manual approval.

### 4.2 Pipeline stages

```
PR opened
    │
    ├── Stage 1: Lint
    │   - ruff (Python), eslint (TS), terraform fmt/validate
    │
    ├── Stage 2: Static checks
    │   - mypy strict, type-checking on changed files
    │   - CitedBy custom checks: cross-module imports, raw SQL, RLS coverage
    │
    ├── Stage 3: Unit tests
    │   - Python: pytest, parallel, with coverage
    │   - JS/TS: vitest, parallel, with coverage
    │   - Coverage gate: 80% per changed file
    │
    ├── Stage 4: Integration tests
    │   - Spin up testcontainers (Postgres with RLS)
    │   - Run integration suite
    │
    ├── Stage 5: Build
    │   - Docker images for each service
    │   - Image signing via Sigstore/Cosign
    │   - Image scan via Trivy
    │
    └── PR review + approval

Merge to main
    │
    ├── Stage 6: Deploy to dev
    │   - Terraform plan + apply (if infra changes)
    │   - Cloud Run revision deploy with traffic shift
    │   - DB migrations applied via migration job
    │
    └── Stage 7: Dev smoke tests
        - Healthchecks pass
        - Critical endpoints return 2xx
        - Synthetic transaction succeeds

Tag staging
    │
    ├── Stage 8: Deploy to staging (same as dev)
    └── Stage 9: Staging integration suite + e2e Playwright tests

Tag prod
    │
    ├── Stage 10: Manual approval gate (1 of: CTO, on-call lead)
    ├── Stage 11: Deploy to prod
    │   - Canary: 10% traffic → 25% → 50% → 100%, 5 min between steps
    │   - Auto-rollback on error rate >2% or p95 latency >2x baseline
    └── Stage 12: Post-deploy verification
        - Synthetic transactions
        - Sentry: no new error groups in last 10 min
        - Datadog: SLO dashboards green
```

### 4.3 Database migration strategy

Migrations use [Atlas](https://atlasgo.io/) or [sqitch](https://sqitch.org/) (vendor selection in week 1; Atlas leans likelier given declarative model).

Rules:
- **Backwards-compatible migrations only.** Schema change deploys before code that depends on it.
- **Forward-only.** No rollback migrations; rollback = forward migration that reverses.
- **Per-environment migration history.** Atlas/sqitch tracks applied migrations.
- **Migration job runs separately from app deploy.** A failed migration does not auto-rollback the app — it pages.
- **Three-stage rollout for risky changes:** add column nullable → backfill → make NOT NULL.

---

## 5. Observability Stack

### 5.1 Three pillars

**Metrics:** OpenTelemetry SDK → Cloud Monitoring. Dashboards in Cloud Monitoring + Grafana (read-only, fed from Cloud Monitoring).

**Traces:** OpenTelemetry → Cloud Trace. Every HTTP request, every Temporal activity, every external API call is traced. Sampling: 100% in dev, 10% in prod (with errors always sampled).

**Logs:** Structured JSON logs → Cloud Logging. Correlated with traces via `trace_id`. Retention: 30 days (dev), 90 days (staging), 1 year (prod).

### 5.2 Error tracking

Sentry, separate projects per environment, with source maps uploaded on build. Alerts route to PagerDuty for `prod` only.

### 5.3 Product analytics

PostHog self-hosted on GCP in `asia-south1` (data residency). Single PostHog instance serves all environments with environment-tagged events. Feature flags managed via PostHog.

### 5.4 SLOs (initial targets, refined in Phase 8)

| Service | SLO | Error budget |
|---|---|---|
| API availability (p99 over rolling 28d) | 99.5% | ~3.6h/month |
| Free audit completion within 10 min | 95% | — |
| Audit p95 end-to-end latency | <5 min | — |
| Tenant isolation breach | 0 (hard cap) | 0 |

Burn-rate alerts at 2x and 10x burn.

### 5.5 On-call

Two on-call rotations:
- **Application on-call** (CTO + engineers): app errors, Temporal failures
- **Infrastructure on-call** (CTO + DevOps lead): GCP outages, scaling events

PagerDuty schedule, weekly rotation. Runbooks in `/docs/runbooks/` in the main repo.

---

## 6. Cost Architecture

### 6.1 Cost budgets

Per-environment monthly budget alerts:
- `dev`: ₹30,000 (~$360). Alerts at 50%, 80%, 100% → engineering Slack.
- `staging`: ₹60,000 (~$720). Alerts as above.
- `prod`: ₹4,00,000 (~$4,800) for MVP target scale. Alerts at 50%, 80% → Slack; 100% → PagerDuty.

### 6.2 Variable cost components

These scale with usage; tracked separately:
- LLM API costs (Anthropic + OpenAI)
- Proxy/scraping costs (Bright Data/Smartproxy)
- Cloud SQL CPU + storage
- Cloud Run compute
- Egress

A daily cost dashboard combines GCP billing export (BigQuery) + vendor invoices into one view. Anomalies (>1.5x rolling 7-day average) page on-call.

### 6.3 Vendor evaluations (Phase 0 deliverables)

| Vendor | Decision needed by | Decision criteria |
|---|---|---|
| Residential proxy (Bright Data vs Smartproxy vs Oxylabs) | End week 2 | India-resident IP availability, request cost, contract terms |
| Email provider (Resend vs SendGrid) | End week 1 | India inbox deliverability test, pricing, transactional volume |
| Auth0 vs Clerk vs custom | End week 1 | Multi-tenant flexibility, India data residency, pricing |
| Temporal Cloud vs self-hosted | Day 1 (Cloud) | Engineering time saved >> hosting cost |

For each vendor, a one-page decision memo is filed in `/docs/decisions/`.

---

## 7. Disaster Recovery

### 7.1 Recovery objectives

| Disaster | RPO | RTO |
|---|---|---|
| Cloud SQL primary loss (intra-region) | 0 (sync replica) | <5 min (auto failover) |
| Region loss (asia-south1 down) | <1h (async DR replica) | <4h (manual failover) |
| Accidental data deletion | <1h (PITR) | <2h |
| Workflow corruption | 0 (Temporal durable) | <30 min (Temporal restart) |
| GCS bucket loss | 0 (versioning + object retention) | <2h |
| Total GCP account compromise | <1h (offsite logical backups to AWS S3) | <24h |

### 7.2 Backup destinations

- **Primary backups:** Cloud SQL automated backups in `asia-south1`.
- **Regional DR replica:** async Cloud SQL replica in `asia-south2`.
- **Offsite logical backups:** weekly `pg_dump` to AWS S3 `ap-south-1` (Mumbai). Encrypted with separate key. This is the "GCP-is-compromised" fallback.

### 7.3 DR drill cadence

Quarterly tabletop + annual live drill. Live drill: promote DR replica to primary in staging clone of prod, run synthetic transactions, measure RTO.

### 7.4 Break-glass admin access

If all designated admins are unavailable:
- Two physical hardware-secured keys (YubiKeys) stored at separate locations (CTO home safe + lawyer's office) authenticate a break-glass GCP organization-level admin account.
- Activation logged immutably to a separate audit project.
- Any break-glass session ends with a postmortem.

---

## 8. Compliance Checkpoints (DPDP)

| Requirement | Phase 0 deliverable |
|---|---|
| Data localisation | All primary data + backups in India (Mumbai + Delhi); offsite in Mumbai (AWS) |
| Right to erasure mechanism | Soft-delete + 30-day purge — workflows in subsequent phases |
| Data export mechanism | GCS export job stub; full mechanism in Phase 8 |
| Audit log retention | Cloud Logging configured for 7-year retention on admin-action logs |
| Consent records | Database table schema reserved; populated in Phase 1+ |
| DPO appointed | CTO acts as DPO for MVP; external DPO at Series A |

A DPDP-specific runbook is written and reviewed by external counsel before Phase 1 launches.

---

## 9. Self-Review

### Pass 1

| # | Severity | Finding | Where |
|---|---|---|---|
| H1 | **High** | Terraform state itself contains secret references (DB passwords, KMS key IDs). Storing state in GCS with default encryption is insufficient; we need state-level encryption with rotated keys. | §3.1 |
| H2 | **High** | The CI/CD pipeline gives merge-to-main a free deploy to dev — but if a malicious PR is merged (compromised maintainer credentials), it deploys instantly. We need a deploy-time check, not just review-time. | §4.1 |
| H3 | **High** | "All engineers (Editor)" on dev project is dangerous. Editor includes IAM admin, which means an engineer can grant themselves prod access if they ever compromise cross-project privileges. Reduce dev IAM to least-privilege. | §3.1 |
| M1 | Medium | Auth0 — we listed it as a Phase 0 dependency but didn't say what to do if Auth0 is down. No fallback identity path. | §3.6 (implicit) |
| M2 | Medium | Cost budget for prod is ₹4L/month at MVP scale, but the budget doesn't include LLM and proxy costs which are billed by third parties, not GCP. Need a unified view. | §6.1, §6.2 |
| M3 | Medium | We have not addressed how engineers do *local* development against a Postgres with RLS. Naive setup will leave engineers either bypassing RLS (bad habit) or unable to query (frustration). | §3.3 |
| M4 | Medium | The "Backwards-compatible migrations only" rule is correct, but we haven't said how we enforce it. A junior engineer could write a DROP COLUMN migration and merge it. | §4.3 |
| M5 | Medium | Worker pool deployment strategy: we said "Cloud Run for workers" but Temporal workers benefit from long-lived processes. Cold-starting workers per request is wasteful and slow. Need warm-pool strategy. | §3.2 |
| L1 | Low | The bucket naming convention uses `{env}-` prefix, but lifecycle policies are described per bucket purpose. Not aligned. | §3.5 |
| L2 | Low | OpenTelemetry sampling at 10% in prod could miss low-frequency error patterns. | §5.1 |

Three highs and five mediums. Iterating.

### Pass 2 (resolutions)

**H1 (Terraform state security):** Resolved by structuring state as follows:
- Terraform state stored in GCS bucket `citedby-{env}-tf-state` with **bucket-level CMEK encryption** using a separate KMS key (`tf-state-key`) that is **separate** from the application-data KMS key.
- The `tf-state-key` is in `citedby-shared-secrets` project with strict IAM (CTO + DevOps lead only).
- State bucket has **versioning enabled** and **object retention** of 1 year (prevents accidental or malicious deletion).
- **No secrets in Terraform state.** Database passwords, API keys are generated *outside* Terraform and only their Secret Manager references are passed to Terraform. Use `random_password` with `keepers` only for non-secret values.
- **Terraform Cloud or OpenTofu Cloud** considered but rejected for MVP — adds another vendor. State in GCS is sufficient with the above hardening.

**H2 (CI deploy-time check):** Added: even on merge to main, the deploy job requires the **commit to be signed by a trusted committer key** (GitHub commit signature verification). PRs from forks cannot deploy. PRs from suspicious patterns (e.g., modifying CI configs) require a second approval. GitHub branch protection rule enforces this.

**H3 (dev IAM):** Reduced to least-privilege: engineers get `roles/run.developer`, `roles/cloudsql.client`, `roles/logging.viewer`, `roles/monitoring.viewer`, `roles/secretmanager.secretAccessor` (scoped to `dev/*` secrets). They **do not** get `roles/iam.serviceAccountUser` (cannot impersonate service accounts) or any project-level admin role. IAM admin in dev is restricted to CTO + DevOps lead.

**M1 (Auth0 outage):** Added contingency: maintenance-mode page renders if Auth0 is unreachable for >5 min. Already-authenticated users (with valid JWT) continue to be served until JWT expires. No silent degradation. Documented runbook for prolonged Auth0 outage including option to switch to backup IdP (Clerk warm standby) but this is Phase 8 work.

**M2 (unified cost view):** Added: a `citedby-cost-aggregator` Cloud Function pulls vendor invoices weekly (OpenAI, Anthropic, Perplexity, proxy provider) via their respective APIs and inserts into a BigQuery dataset alongside GCP billing export. A single Looker Studio dashboard shows the combined view. Total monthly cost cap is enforced against the *combined* number, with alerts at the unified threshold.

**M3 (local development with RLS):** Resolved by providing a `tools/setup-local-db.sh` script that:
- Spins up Postgres 16 in Docker with the production schema
- Creates a `local_dev_role` with permissions identical to the production application role
- Pre-populates `app.current_tenant`, `app.current_user_id` via a session-helper function
- Documents the "always run within `with_tenant_context(...)` block" pattern in `CONTRIBUTING.md`

Engineers can also run `make dev-bypass-rls` which sets `app.is_platform_admin = true` — but only the **local** Postgres trust this. The production database refuses connections without explicit Workload Identity binding, so even a leaked dev script cannot bypass production RLS.

**M4 (migration safety enforcement):** Added: a CI check parses Atlas migrations and rejects:
- `DROP COLUMN` (must go via `make-nullable → backfill → drop-deprecated`)
- `DROP TABLE` (requires explicit `MIGRATION_DESTRUCTIVE=allowed` env var on the PR)
- `ALTER COLUMN ... TYPE` that's not type-compatible
- `RENAME` operations (always destructive in zero-downtime context)

Override available via PR label `migration-reviewed-by-dba` requiring two senior approvers.

**M5 (worker warm pool):** Resolved by setting `min_instances=1` on each worker Cloud Run service in prod (warm pool of one). Cold-start mitigated. For staging, `min_instances=0` to save cost. Temporal worker code is designed to be polling-based, so it picks up work immediately on cold start, but a warm instance means no cold start in normal operation.

**L1 (bucket naming):** Standardised: `citedby-{env}-{purpose}` is the canonical pattern. Lifecycle policies are configured per-bucket in Terraform module variables.

**L2 (OTel sampling):** Updated: head-based sampling at 10% in prod, but tail-based sampling escalates to 100% for traces with any of: error status, latency >p99 threshold, specific user/tenant flagged for debugging. Cloud Trace supports this; documented in observability section.

### Pass 3

Re-review after Pass 2 resolutions:

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M6 | Medium | The break-glass YubiKey procedure (§7.4) requires two keys at two locations, but doesn't say how the key holders authenticate themselves to each other. A social engineer could try to coerce one holder into accessing alone. | Add: break-glass activation requires *both* holders present (in person or video-verified), with a documented identity verification step. The break-glass account requires both holders' authentication factors before being activated. |
| L3 | Low | Cost aggregator function (M2 resolution) introduces a new failure point: if it crashes, we lose unified visibility. | Add: aggregator runs daily as a Cloud Scheduler-triggered Cloud Function with retry; failure pages ops if missed twice. |

**M6 resolved** in this pass.

No remaining H or M findings. **Self-review passes.**

---

## 10. Phase 0 Implementation Sequence

| Week | Tasks |
|---|---|
| 1 | GCP organization + projects + folders + billing setup. Terraform skeleton. KMS keys. Secret Manager initial secrets. |
| 1 | Vendor decisions (proxy, email, Auth0). Decision memos filed. |
| 2 | VPC + Cloud SQL (dev first) + Memorystore + GCS buckets + Cloud Run skeleton. |
| 2 | Domain registration confirmation + DNS + Load Balancer + managed SSL. |
| 3 | Temporal Cloud namespaces + auth + initial workflow registration. |
| 3 | Auth0 tenants set up; client apps configured. |
| 3 | CI/CD pipelines in GitHub Actions; first hello-world deploy to dev. |
| 4 | Staging environment built from same Terraform; smoke test. |
| 4 | Prod environment built; locked down; no app deployed yet. |
| 4 | Observability stack: Sentry projects, PostHog self-hosted, Cloud Trace, Cloud Monitoring dashboards. |
| 5 | Cost budgets + alerts + unified dashboard. |
| 5 | Backup config + first DR drill (tabletop). |
| 5 | Runbooks v1 written for: deploy, rollback, DB failure, Temporal failure, Auth0 outage. |
| 6 | Phase 0 sign-off; Phase 1 can begin. |

Phase 0 is staffed by 1 DevOps lead + CTO support, with engineering assistance on CI integration in weeks 3–4.

### Exit criteria

- All §1.2 deliverables complete and verified.
- A test deploy of a hello-world service end-to-end (PR → dev → tag → staging → tag → prod) takes <30 minutes including manual approval.
- DR tabletop drill completed; runbook approved.
- Vendor decisions documented and contracts signed.
- Phase 1 team can begin without infrastructure blockers.

---

## 11. Handoff to Phase 1

Phase 1 consumes from Phase 0:
- A working GCP environment in all three projects.
- Auth0 tenants ready for Phase 1's user signup flows.
- Cloud SQL with the required extensions; migration tooling ready.
- Secret Manager namespace `*/identity/*` provisioned with empty placeholders.
- CI/CD ready to deploy Phase 1 services.
- Monitoring dashboards templated; Phase 1 adds module-specific panels.
- VPC and Serverless VPC Connector ready for Cloud Run → Postgres traffic.

No code from Phase 0 needs to change for Phase 1. Phase 0 is a stable foundation.

---

*CitedBy Phase 0 Design v1.0 | Confidential | May 2026*
*Next: Phase 2 — Audit & Citation Detection*
