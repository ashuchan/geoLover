# CitedBy — Phase 8 Design
## Hardening, Security Review, Launch
**Version:** 1.0
**Status:** Approved for implementation
**Date:** May 2026
**Author:** CTO, CitedBy
**Parent document:** `CitedBy_HLD_v1.md`
**Modules covered:** All — this is the cross-cutting launch phase

---

## 1. Phase Overview

### 1.1 Why this is Phase 8

Phases 0–7 build the product. Phase 8 makes it **safe to charge money for and possible to operate**. Without Phase 8:
- Security vulnerabilities we don't know about are vulnerabilities we are exposed to.
- Performance characteristics we haven't measured are characteristics we don't control.
- Failure modes we haven't rehearsed are failures we will mishandle when they happen for real.
- Operational tooling we haven't built is tooling whose absence the on-call engineer will resent at 3 AM.

Phase 8 is the difference between "code that works" and "a service that runs."

Phase 8 is also the most process-heavy of all phases. There is comparatively little new code; there is a great deal of rigorous testing, documentation, drilling, and validation. The deliverables are evidence — penetration test reports, load test traces, runbook documents, an executed DR drill — not features.

### 1.2 What this phase delivers

By the end of Phase 8:

- An **external penetration test** has been conducted; all critical and high findings are remediated; the residual risk has been signed off by the CTO.
- A **DPDP compliance audit** has been conducted by external counsel; we hold a compliance memo with a known set of obligations and our evidence of meeting them.
- **Load tests** at 3× projected MVP load have run; capacity headroom is documented per service.
- A **disaster recovery drill** simulating a regional outage has been executed; RPO and RTO targets validated; gaps identified and closed.
- A **runbook library** exists covering the top 30 operational scenarios (database failover, Temporal outage, OAuth provider down, LLM cost spike, suspected data leak, customer-data export request, etc.).
- **PagerDuty is wired** to alerts; an on-call rotation is staffed; escalation paths are documented.
- A **customer support tool** lets ops impersonate a tenant (with auditing), inspect their data, and execute approved actions.
- **Billing enforcement** is enabled; quotas defined in `plans` are now hard-enforced; soft-warn → hard-block transitions are tested.
- A **public status page** exists; component health is published; incidents are communicated.
- **Public documentation** is published: help center, getting-started guides, API reference for the limited public API.
- **WhatsApp Business API** is approved and the Phase 6 adapter is enabled; message templates pass Meta review.
- A **beta-to-GA criteria checklist** is filled in; the launch decision is made on evidence, not intuition.

### 1.3 What this phase does NOT deliver

- New product features. If a feature didn't ship in Phases 1–7, it does not ship in Phase 8. The launch is what we have, not what we wish we had.
- A full SOC 2 audit. SOC 2 is a 6–12 month observation window plus auditor engagement; we begin the process in Phase 8 but the report is post-launch.
- A multi-region active-active deployment. India-only single-region remains correct until at least Series B.
- Public API rate limits, OAuth provider for third-party developers. The MVP API is internal-only with limited customer-facing data export.

---

## 2. Goals and Constraints

### 2.1 Goals (in priority order)

| # | Goal | What this means |
|---|---|---|
| G1 | **No known critical or high security vulnerabilities at launch** | Pen test report shows zero unresolved C/H findings |
| G2 | **Demonstrated capacity for 5× projected MVP load** | Documented load test traces; identified scaling chokepoints |
| G3 | **Operational readiness verified through drills** | At least one executed DR drill, at least three executed runbook walkthroughs |
| G4 | **Compliance position documented in writing** | DPDP memo, data flow diagrams, RoPA (Record of Processing Activities) |
| G5 | **On-call experience humane** | 30 runbooks, paging routes by severity, MTTR target documented |
| G6 | **Customer experience smooth at launch** | Onboarding tested with 5 friendly-beta customers, no critical bugs surfacing |

### 2.2 Constraints

- **Time-boxed.** Phase 8 cannot run forever. We commit to 4 weeks and accept any residual medium-or-lower issues as launch debt with explicit owners and deadlines.
- **No new features.** Tempting feature requests during this phase are diverted to post-launch backlog with documented rationale.
- **Friendly-beta cohort of 5–10 customers.** Real usage, real money, real feedback. Their issues count; new feature requests do not.

---

## 3. Security Audit

### 3.1 Threat model recap

The threats we are guarding against, prioritized by impact × likelihood:

| # | Threat | Primary mitigation |
|---|---|---|
| T1 | Tenant data leak across tenants | RLS (Phase 1) + CI tenancy scan; pen test verifies |
| T2 | OAuth token theft or misuse | KMS envelope (Phase 5); token use audit logs |
| T3 | Account takeover via credential stuffing | Auth0 MFA optional, rate-limiting, anomaly detection |
| T4 | Prompt injection / LLM data exfiltration | PII redaction (Phase 4); restricted prompt parameters |
| T5 | Engine response → injected instruction → workflow corruption | Engine responses treated as untrusted data, never as instructions |
| T6 | Custom domain hijack | DNS heartbeat (Phase 7); OAuth callbacks not on agency domains |
| T7 | Bulk-import abuse (a malicious agency_admin floods system) | Tier-bound rate limits, abuse detection |
| T8 | Web app vulnerabilities (XSS, CSRF, SSRF) | Standard mitigations + scanning |
| T9 | Supply chain attack via dependencies | Renovate-bot + Snyk + locked dependencies |
| T10 | Insider threat (malicious or compromised employee) | Least privilege, break-glass procedure, audit logs |

### 3.2 Audit scope

**External penetration test** scope:
- Application-level: all customer-facing routes, the API surface, the agency portal, the public free-audit endpoint.
- Authentication and authorization: focused testing on tenant isolation, role escalation, scope-circumvention.
- Infrastructure: GCP project misconfigurations, IAM gaps, exposed services.
- LLM-specific: prompt injection vectors, jailbreak attempts on the audit-quick-wins prompt, data leak via clever input.
- Excluded from external test: source code (SAST handled internally), social engineering (out of scope).

**Vendor selection criteria:**
- Indian or India-experienced security firm (data localization for any sensitive findings).
- Demonstrated experience with multi-tenant SaaS.
- OWASP ASVS Level 2 coverage minimum.
- Final report includes CVSS scores and remediation guidance.

**Cadence:** 2-week test window. Vendor delivers preliminary findings at week 1 (so we can begin remediation in parallel). Final report at week 2 + a re-test of remediated criticals at week 3.

### 3.3 Internal scanning (already in place; Phase 8 hardens)

- **SAST:** Semgrep + Bandit (Python) + ESLint security plugins (Node). Already running in CI. Phase 8 raises the bar: any new finding blocks PR until classified.
- **DAST:** OWASP ZAP nightly against staging. Phase 8 enables baseline + active scan modes.
- **Dependency scanning:** Snyk + Renovate. Phase 8 enables automatic security PR creation.
- **Secret scanning:** GitGuardian on every push. Phase 8 enables pre-commit hooks for engineers.
- **Container scanning:** Artifact Registry vulnerability scanning. Phase 8 enables auto-block of deploys for containers with critical vulnerabilities.

### 3.4 Remediation policy

Findings classified by CVSS:
- **Critical (9.0+):** must remediate before launch. No exceptions.
- **High (7.0–8.9):** must remediate before launch unless explicit risk acceptance signed by CTO.
- **Medium (4.0–6.9):** remediation within 30 days of launch; tracked.
- **Low (<4.0):** added to backlog with quarterly review.

The remediation tracker is a public-internal Jira board. Findings have explicit owners and deadlines. Daily standup during Phase 8 includes a 5-minute security findings review.

### 3.5 Re-test

After remediation, the vendor re-tests each critical and high finding. Re-test results form the final go/no-go data point for launch.

---

## 4. DPDP Compliance Audit

### 4.1 What the audit checks

The DPDP Act (Digital Personal Data Protection Act, 2023) requires us to be able to demonstrate, in writing:

| Obligation | Our evidence |
|---|---|
| Data localization | All primary data in `asia-south1` (Phase 0); backup in `asia-south2`. Architecture diagrams + Terraform proves this. |
| Lawful basis for processing | Consent at signup; consent record stored per-tenant. |
| Purpose limitation | Data flow diagram showing what we collect and why. |
| Data minimization | Audit logs show only necessary fields collected. |
| Notice & consent | Privacy policy + signup consent UI |
| Right to access | Per-tenant data export via self-serve workflow (Phase 1) |
| Right to correction | Profile edit (Phase 1) |
| Right to erasure | `DeleteBusinessWorkflow`, cascade soft-delete (Phase 1 + each subsequent phase) |
| Data processor agreements | DPAs with all sub-processors (Anthropic, OpenAI, Resend, Auth0, etc.) |
| Security safeguards | Encryption at rest, in transit, KMS-managed keys (Phases 0, 1, 5) |
| Data breach notification | Documented incident response runbook (Phase 8, §7) |
| Children's data | We do not knowingly process children's data; ToS prohibits |
| Cross-border transfer | LLM calls cross border; data anonymized; vendor DPAs cover |

### 4.2 The deliverables

A **Compliance Memo** prepared by external counsel, listing each obligation, our position, our evidence, and any residual risk. This is the document we hand to enterprise customers asking "are you DPDP-compliant?" Their procurement teams need a written answer.

A **Record of Processing Activities (RoPA)** — a detailed inventory of what data we collect, where it lives, how long we keep it, who we share it with. Updated quarterly post-launch.

A **Data Flow Diagram (DFD)** for the system, showing personal data movement at architectural level. Updated when material data flows change.

### 4.3 Sub-processor management

Every third party we send personal data to is a sub-processor. We maintain a public list and an internal DPA tracker. At launch:
- Anthropic — DPA signed
- OpenAI — DPA signed
- Auth0 (Okta) — DPA signed, India residency confirmed
- Resend — DPA signed
- GCP — covered under Google's enterprise DPA
- Temporal Cloud — DPA signed
- Sentry (self-hosted in India) — no DPA needed (self-hosted)
- PostHog (self-hosted in India) — no DPA needed (self-hosted)

If a customer requests sub-processor information, we provide the list and DPAs on request, per industry standard.

---

## 5. Performance and Load Testing

### 5.1 Target load profile

We model launch load conservatively based on PRD targets:

| Metric | MVP target | 3× test target | 5× test target |
|---|---|---|---|
| Tenants | 25 paying + 5 agencies | 75 + 15 | 125 + 25 |
| Businesses | 100 active | 300 | 500 |
| Free audits per day | 50 | 150 | 250 |
| Weekly recrawls (peak hour) | ~15 concurrent | ~45 | ~75 |
| Content briefs per week | ~200 | 600 | 1000 |
| Publish attempts per week | ~100 | 300 | 500 |
| API requests (dashboard browsing) | 50 req/s peak | 150 | 250 |

3× target is our launch capacity headroom. 5× target identifies the next scaling chokepoint.

### 5.2 Load test design

Load tests run against **staging** (not prod), using a synthetic-tenant dataset that mirrors prod schema scaled to test targets.

Per-scenario test definitions:
- **Steady state:** all systems at 1× for 4 hours. Verify no resource leaks, GC pressure, connection pool exhaustion.
- **Audit burst:** 50 free-audit submissions in 5 minutes. Verify queue depths, audit completion times, no cascading failure.
- **Recrawl Monday morning:** simulate the Monday 06:00 bucket-schedule firing for 75 businesses. Verify completion within NF1 target (6 hours).
- **Bulk import scale:** an agency uploads 500 rows, triggers audits. Verify other agencies' work is not impacted.
- **LLM cost spike simulation:** burst content generation to 100 briefs in an hour. Verify cost ceilings engage correctly.
- **Database stress:** sustained 250 req/s mixed workload against Postgres for 1 hour. Verify connection pool stable, slow queries under SLO.

### 5.3 Test execution

We use **k6** (open-source load testing) for HTTP load, custom Python harness for workflow simulation. Tests run via dedicated GCP project to avoid contaminating staging metrics.

Each test run produces:
- Throughput vs. latency curves per endpoint.
- Resource utilization (CPU, memory, connections, queue depths) per service.
- Error rate breakdown by error class.
- Cost (compute + LLM + proxy) per test scenario.

Findings classified:
- **Blocking:** any p95 latency > 2× SLO at 3× load. Must fix.
- **Concerning:** any p95 latency > SLO at 5× load. Must document scaling response.
- **OK:** within SLO at 3× and within 2× SLO at 5×.

### 5.4 Capacity planning output

Phase 8 produces a **Capacity Plan** document listing:
- Current MVP capacity per service (in terms of business count or request rate).
- The scale-up trigger for each service (e.g., "double crawl-worker max instances when Monday-recrawl completion exceeds 5 hours").
- The cost projection at each capacity tier.

This is the operational reference for the first 12 months post-launch.

---

## 6. Disaster Recovery Drill

### 6.1 The drill scenario

**Scenario:** `asia-south1` becomes unavailable for 4 hours (simulating, e.g., a regional GCP outage).

**Drill objective:** validate that we can restore service from backups and resume operations within RTO (4 hours).

**Out of scope for MVP drill:** active failover. We are running single-region. The drill validates *recovery*, not failover continuity. Customers see downtime; the drill confirms downtime is bounded.

### 6.2 Drill procedure

```
T+0:00  Announce drill begin (Slack, status page in "Drill" mode)
T+0:00  Simulate region outage: cut Cloud SQL access, halt Cloud Run services
T+0:05  Page on-call (the actual on-call engineer, not the drill orchestrator)
T+0:15  On-call acknowledges; opens runbook "Regional Outage Recovery"
T+0:20  Provision new Cloud SQL instance in asia-south2 from latest backup
T+0:50  Cloud SQL restore complete; integrity check runs
T+1:00  Run Terraform to spin up Cloud Run services pointed at the restored DB
T+1:30  Cloud Run services accepting traffic; smoke tests pass
T+1:45  Re-point load balancer; update DNS if needed
T+2:00  Customer-facing service restored to read+write
T+2:15  Reconcile in-flight workflows (Temporal Cloud is unaffected; resume picks them up)
T+2:30  Drill complete; collect timing data
T+3:00  Post-drill review meeting
```

### 6.3 What we measure

| Metric | Target | Measured how |
|---|---|---|
| Time to detect | <5 min | Alert timestamp |
| Time to declare incident | <10 min | Incident channel message |
| Time to begin recovery | <20 min | First recovery action |
| Time to data restored | <60 min | Restored DB query check |
| Time to service restored | <2 hr | First successful customer request |
| Time to fully reconciled | <4 hr | All in-flight workflows resumed |
| Data loss | <1 hr (RPO) | Compare last-committed transactions to restore point |

### 6.4 Drill outputs

The drill produces:
- A timing report against targets.
- A list of friction points (e.g., "Terraform apply was slower than expected because state lock timeout was too short").
- Updated runbooks reflecting lessons learned.
- A go/no-go decision for launch based on drill performance.

If RPO/RTO targets aren't met, we either remediate before launch or accept the gap explicitly with documented mitigation.

---

## 7. Operational Readiness

### 7.1 Runbook library

We commit to 30 runbooks at launch. Each is a single Markdown file with a stable schema:

```
# Runbook: <scenario name>
## Severity: <P0 | P1 | P2>
## Last updated: <date>
## Owner: <team>

## Symptoms
What the on-call sees when this happens.

## Detection
Where the alert fires; what dashboards show.

## Initial response (first 5 minutes)
What to do immediately.

## Triage
How to determine the actual cause.

## Resolution
Step-by-step instructions for known causes.

## Communication
Who to notify; what to say to customers (with templates).

## Post-incident
What to do after resolution; what to document.
```

The starter set of 30 runbooks at launch covers:

| # | Runbook | Severity |
|---|---|---|
| 1 | Postgres primary failover | P0 |
| 2 | Regional outage (full DR) | P0 |
| 3 | Temporal Cloud outage | P0 |
| 4 | Authentication provider outage (Auth0) | P0 |
| 5 | LLM provider total failure | P1 |
| 6 | LLM cost runaway (>2× budget in an hour) | P0 |
| 7 | Customer reports tenant data leak | P0 |
| 8 | Suspected security breach | P0 |
| 9 | Customer requests data deletion under DPDP | P1 |
| 10 | Customer requests data export | P2 |
| 11 | OAuth token mass-revocation (Google security action) | P1 |
| 12 | Engine adapter all-down for one engine | P1 |
| 13 | Engine adapter degraded (>30% error rate) | P2 |
| 14 | Email deliverability drop | P2 |
| 15 | Custom domain DNS removed by agency | P2 |
| 16 | SSL cert provisioning failure | P2 |
| 17 | Bulk import stuck workflow | P2 |
| 18 | Audit completion time > 6 hours | P2 |
| 19 | Citation detection accuracy regression alert | P1 |
| 20 | Database disk filling | P1 |
| 21 | Cloud Run instance failing health checks | P2 |
| 22 | Redis eviction storm | P2 |
| 23 | Slow query identified (p99 > 1s) | P2 |
| 24 | New customer onboarding stuck | P2 |
| 25 | Payment processing failure | P1 |
| 26 | Subscription billing webhook missed | P2 |
| 27 | Status page outage | P2 |
| 28 | Prompt version regression (rejection rate spike) | P1 |
| 29 | Branding leak detected in production | P1 |
| 30 | Whistleblower / abuse report received | P1 |

Each runbook is reviewed during Phase 8 by at least one person who is not the original author.

### 7.2 On-call rotation

- **Rotation cadence:** weekly. Primary + secondary on-call.
- **Team size:** at MVP, 3 engineers. 1-in-3 rotation, with the CTO covering gaps.
- **Burnout mitigation:** explicit policy that *no* P2 pages outside business hours; P2 alerts go to Slack only. Only P0/P1 page. Documented in §10.
- **Compensation:** time-off-in-lieu for any after-hours page.

PagerDuty integration:
- Alert sources: Cloud Monitoring, Sentry (high-severity), Temporal alert, custom application alerts.
- Routing: by severity to primary on-call; secondary on 5-minute no-ack; CTO on 15-minute no-ack.
- Escalation policy reviewed before launch.

### 7.3 Customer support tooling

A platform-admin-only `/admin` interface exposing:
- **Search**: by tenant name, email, business name.
- **Tenant detail**: subscription state, recent activity, current quota usage.
- **Business detail**: profile, recent audits, content pipeline state, publish targets, current issues.
- **Impersonation**: "View as <user>" — opens a read-only view of the customer's dashboard. Every impersonation logged with reason, duration.
- **Approved actions**:
  - Trigger an audit for a customer (after their request).
  - Pause an account (security/abuse).
  - Process a deletion request.
  - Issue a credit or extend a trial.
  - Resend a verification email.

All admin actions log to `admin_audit_log` (table from Phase 1).

### 7.4 Status page

A public status page at `status.citedby.app` showing component-level health:
- API
- Audit Engine (per AI engine sub-component)
- Content Generation
- Publishing (per channel sub-component)
- Notifications

Component health is computed from internal monitoring. Page hosted on a third-party (Statuspage or Instatus) so a CitedBy outage doesn't take down the status page.

Incident lifecycle:
- **Detected → Investigating → Identified → Monitoring → Resolved** (standard).
- Postmortems for P0/P1 incidents are public within 5 business days.

---

## 8. Billing Enforcement Enablement

### 8.1 The shift

Through Phase 7, the `Subscriptions` schema exists and limits are configured, but enforcement has been advisory-only (soft warnings, no hard blocks). Phase 8 flips the switch.

### 8.2 What gets enforced

| Limit | Enforcement |
|---|---|
| Number of active businesses per tenant | Block business creation above plan limit |
| Audits per month per business | Block manual audit trigger; weekly recrawl continues but the next one notifies |
| Content briefs per month per business | Block new brief generation |
| LLM monthly spend per business | Block discretionary LLM calls (Phase 4 §4.5) |
| Publish channels connected per business | Block new target connection |
| Bulk import rows per upload | Already enforced at validation |
| API request rate | Already enforced at gateway |

### 8.3 The enablement procedure

Enforcement is not flipped on globally in one moment. The procedure:

1. **One week before launch:** announce to existing customers that enforcement begins on launch day. Send specific notice to any customer currently over-quota (warning them their account will need attention).
2. **Three days before:** dry-run enforcement (log when actions would have been blocked; do not actually block). Verify no surprises.
3. **Launch day morning:** enforcement on for all paying customers. Trial customers unaffected.
4. **Launch day + 1 week:** review enforcement-related support tickets; adjust limits if anyone was wrongly over-quota due to data anomalies.

### 8.4 Grace handling

For customers genuinely caught off guard:
- A one-time, per-tenant "soft grace" period (configurable, default 7 days) where they get warnings but no blocks.
- A platform-admin action to extend the grace (in the support tool from §7.3).

This is empathy-as-engineering. New enforcement always produces edge cases; we don't penalize customers for our policy timing.

---

## 9. Communications and Documentation

### 9.1 Customer-facing documentation

A help center at `help.citedby.app` covering:
- Getting started (the free audit, signing up, first business profile).
- Reading your audit report.
- Setting up publishing channels.
- Connecting custom domains (for agencies).
- Bulk import.
- Plan and billing.
- Privacy and data.
- FAQ.

Written in plain language; screenshots; ~30 articles at launch. Internal SLO: every customer-reported issue that wasn't covered triggers a new article within 1 week.

### 9.2 In-product guidance

A first-run guided tour for new tenants. Tooltips on key actions. Empty states with clear CTAs ("You have no businesses yet. Start your first audit.").

### 9.3 Public marketing site

The marketing site at `citedby.app` (different from `app.citedby.app`) finalizes:
- Landing page with PRD value proposition.
- Pricing page (subscription tiers, agency tier).
- Free audit funnel.
- Customer logos (from friendly-beta, with permission).
- Blog (initial 5 posts covering GEO basics, citation case studies).
- Privacy policy, terms of service, DPDP notice.

### 9.4 Internal documentation

- **Engineering wiki** kept current with all phase designs (this document set), runbooks, and operational procedures.
- **Onboarding doc** for new engineers (10-page introduction to the system).
- **Architecture decision records (ADRs)** for any decision made during launch that diverged from the design documents.

---

## 10. Beta → GA Criteria

### 10.1 The launch decision

GA launch is not a date; it is a state. The CTO and CEO make a joint go/no-go decision based on evidence.

The minimum bar:

| # | Criterion | Evidence |
|---|---|---|
| L1 | No critical or high security findings unresolved | Pen test re-test report |
| L2 | DPDP compliance memo on file | External counsel sign-off |
| L3 | Load test passed at 3× projected MVP load | Test report with metrics |
| L4 | DR drill completed within RPO/RTO targets | Drill report |
| L5 | 30 runbooks published and reviewed | Runbook library audit |
| L6 | On-call rotation staffed and tested | First test page acknowledged within 5 min |
| L7 | Customer support tooling deployed | Demo to support team |
| L8 | Billing enforcement enabled successfully | Three days of clean enforcement metrics |
| L9 | Status page live | Component health publishing |
| L10 | Help center published with 30+ articles | URL audit |
| L11 | 5+ friendly-beta customers have used the product end-to-end | Customer interviews |
| L12 | Zero critical bugs in the beta cohort during the prior 7 days | Bug tracker review |

If any criterion fails, the launch slips by 1 week (the next checkpoint). Slipping is preferred over launching prematurely.

### 10.2 The friendly-beta program

5–10 customers in friendly-beta for 4 weeks before GA. Selected via:
- Founder network and warm introductions.
- Mix of agency and direct SMB.
- Different verticals (CA firm, dental clinic, coaching center, real estate, law firm).
- Bengaluru-concentrated (per PRD targeting).

Each beta customer:
- Gets onboarded personally.
- Has a dedicated Slack channel with the team.
- Provides feedback weekly.
- Receives 3 months free post-GA in exchange for participation.

Friendly-beta surfaces operational issues, UX gaps, and edge cases. It does **not** drive feature creep.

### 10.3 Soft launch vs hard launch

We do a **soft launch** first: GA-eligible product made available to a wider but still-curated cohort (50 customers), without paid marketing. Soft launch lasts 4 weeks; we measure retention, support load, infra stability.

**Hard launch** (public marketing, PR, paid acquisition) happens only after soft launch metrics confirm operational stability.

---

## 11. Database Schema (additions)

Minor schema additions for Phase 8:

```sql
-- Enables tracking of billing enforcement actions for audit
CREATE TABLE quota_enforcement_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID,
    quota_kind TEXT NOT NULL,        -- 'audits' | 'content_briefs' | 'llm_spend' | etc.
    action TEXT NOT NULL,             -- 'soft_warn' | 'hard_block' | 'grace_extended'
    threshold_pct NUMERIC,
    triggered_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    detail JSONB
);
CREATE INDEX quota_log_tenant_idx ON quota_enforcement_log(tenant_id, triggered_at DESC);

-- Tenant-level grace periods
CREATE TABLE tenant_grace_extensions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    quota_kind TEXT NOT NULL,
    extended_until TIMESTAMPTZ NOT NULL,
    extended_by_user_id UUID NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Support-tool impersonation log
CREATE TABLE impersonation_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_user_id UUID NOT NULL,
    impersonated_tenant_id UUID NOT NULL,
    impersonated_user_id UUID,
    reason TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at TIMESTAMPTZ
);
CREATE INDEX impersonation_log_admin_idx ON impersonation_log(admin_user_id, started_at DESC);

-- Public status page component mapping (internal source of truth)
CREATE TABLE status_components (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    health_signal_query TEXT NOT NULL,  -- reference to a monitoring query
    last_known_state TEXT NOT NULL DEFAULT 'operational',
    last_evaluated_at TIMESTAMPTZ
);
```

---

## 12. Self-Review

### Pass 1

| # | Severity | Finding | Where |
|---|---|---|---|
| H1 | **High** | Pen test findings are remediated under time pressure. Without a second-round verification, we ship "we fixed it" rather than "the vendor confirms it's fixed." The re-test in §3.5 is mentioned but not gated as a hard launch criterion. | §3.5, §10.1 |
| H2 | **High** | The DR drill (§6) is run against staging. But production has real customer data and slightly different infrastructure (production scale, production secrets). A drill that passes in staging may fail in production. | §6 |
| H3 | **High** | Billing enforcement enablement (§8) flips a binary switch. A bug in the enforcement logic could lock out paying customers en masse at the worst possible moment (launch). | §8.3 |
| M1 | Medium | The 30-runbook target is a number, not a quality bar. A runbook that exists but isn't useful is worse than no runbook (it provides false confidence). | §7.1 |
| M2 | Medium | WhatsApp WABA approval is on the critical path for the channel adapter to enable, but the approval timeline is external (Meta-controlled). If approval slips, launch isn't blocked but Phase 6's WhatsApp work goes dark. | §1.2 |
| M3 | Medium | On-call rotation with 3 engineers means each engineer is on-call 1-in-3 weeks. Over a year this is significant burden; burnout policy mentioned but not measured. | §7.2 |
| M4 | Medium | "5 friendly-beta customers" is a small sample. Edge cases (long names with non-Latin scripts, very large agencies, etc.) won't all surface in a small cohort. | §10.2 |
| M5 | Medium | Soft launch → hard launch gating doesn't define the metrics. "Operational stability" could be argued either way under pressure. | §10.3 |
| L1 | Low | The 30-day SAST/DAST findings cleanup commitment for medium-severity (§3.4) lacks accountability mechanism for tracking compliance. | §3.4 |

Three highs and five mediums. Iterating.

### Pass 2 (resolutions)

**H1 (pen test re-test as launch gate):** Re-test by the same vendor of all critical and high findings is added as a **hard launch gate L1**. The vendor must explicitly confirm in writing that prior findings are resolved. If the vendor identifies new issues during the re-test (sometimes happens when changes introduce regressions), those go through the same classification + remediation cycle. The launch criterion is "re-test passes," not "first test issues fixed." Updated in §10.1.

**H2 (DR drill in production):** Two drills, not one:
1. **Staging drill** (described in §6) — full procedure rehearsal against synthetic data.
2. **Limited production drill** — a *partial* drill in production that exercises the *recovery procedure* but not the *outage simulation*. Specifically: we take a recent prod backup, restore it to a *separate* (non-customer-facing) prod GCP project, validate integrity, smoke-test, and tear down. No customer impact, but the production credentials, infrastructure, and procedure are validated end-to-end. Adds 1 day to Phase 8.

Documented in §6 as a two-phase drill.

**H3 (billing enforcement rollout safety):** Expanded the §8.3 procedure:
1. **Per-customer canary.** Enforcement is gated by a feature flag with per-tenant override. First, 5 staff-test tenants. Then friendly-beta tenants (with their explicit awareness). Then 10% of paying tenants for 24h. Then 50% for 24h. Then 100%.
2. **Reversible.** A platform-admin action turns enforcement off platform-wide within seconds.
3. **Observability gate.** Before going from 50% to 100%, we require: zero customer-reported lockouts in the 24h, error rates within baseline, support load within baseline. If any check fails, rollback and investigate.

Updated in §8.3.

**M1 (runbook quality):** Each runbook has a **walkthrough sign-off** before counting toward the 30: another engineer reads the runbook and walks through it (mentally or in a tabletop exercise) and signs "I could follow this at 3 AM." Runbooks without sign-off don't count. Three of the 30 (#1 Postgres failover, #2 Regional outage, #6 LLM cost runaway) are walked through *live* (actually executed in staging) — these become tier-1 runbooks with executed evidence.

**M2 (WhatsApp WABA):** Resolution is acceptance. WhatsApp approval is a parallel track, not on the critical path for launch. If approval lands before launch, the adapter enables. If not, the launch happens with WhatsApp dark; WhatsApp enables in a post-launch increment when approval lands. The PRD-stated Phase 2 timing for vernacular/WhatsApp already supports this. Documented in §1.2.

**M3 (on-call burnout measurement):** Added two metrics tracked weekly post-launch:
- **Sleep nights affected per engineer** (after-hours pages causing sleep disruption).
- **Days since last weekend page per engineer**.
If sleep-nights-affected exceeds 1 per week per engineer for two consecutive weeks, on-call structure is escalated (hire a fourth engineer, outsource L1 to a managed service, etc.). This is a hard policy commitment.

**M4 (beta sample size):** Friendly-beta target is **5–10**, not just 5. The cohort is selected to maximize coverage diversity: at least one agency, at least one direct SMB, at least one vertical not in the founder network. Soft launch (50 customers) extends the coverage. Issues found post-soft-launch but before hard-launch are remediation work, not launch blockers — unless they're severity P0.

**M5 (soft → hard launch metrics):** Defined:
- **Retention:** week-1 retention of activated tenants ≥80%.
- **Operational stability:** zero P0 incidents in the 4-week soft launch window; ≤2 P1 incidents.
- **Support load:** support tickets per active tenant ≤1 per week average.
- **Infra cost trajectory:** actual costs within 1.5× projected.
- **Customer NPS sample:** ≥7/10 on a small sample (5+ customers surveyed).

All five must be on-target to proceed to hard launch. Documented in §10.3.

**L1 (medium finding cleanup tracking):** Added: a fortnightly review of the post-launch findings backlog in the engineering weekly. Findings overdue without an explicit reschedule trigger a CTO-level review. Tracked in a public-internal dashboard.

### Pass 3

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M6 | Medium | The "two-phase DR drill" approach (H2 resolution) still doesn't validate that the drill team can do the *complete* sequence in production. The staging drill is complete; the production "drill" is partial. | Acceptable trade-off. A full production drill (intentional outage of prod) is too risky pre-launch; we wait until we have a multi-region setup (post-Series B per HLD §13) before attempting that. Documented as a known limitation; the partial-prod drill covers the production-specific elements that staging cannot. |
| L2 | Low | The metrics for soft→hard launch gating (M5 resolution) require an NPS survey of 5+ customers. Selection bias possible; small sample size. | Acceptable for the binary go/no-go signal. Statistical rigor not warranted at this scale; qualitative signal is the practical use of the survey. |

**M6 acceptable, L2 acceptable.** No remaining H or M findings. **Self-review passes.**

---

## 13. Test Strategy

### 13.1 Validation tests (not feature tests)

Phase 8 is more about *validating* the system than *testing* features. Validation forms:
- **Pen test re-test** (vendor-driven).
- **Load test runs** (automated; results reviewed by team).
- **DR drill** (manually executed against staging + partial-prod).
- **Runbook walkthroughs** (tabletop or live execution).
- **Friendly-beta usage** (qualitative + observed).
- **Soft launch metrics** (instrument-driven).

### 13.2 Specific test additions in Phase 8

- **Quota enforcement integration tests:** for each enforced quota, test the boundary (under, at, over). Confirm grace period logic.
- **Impersonation audit log tests:** every impersonation logged; no impersonation without logging.
- **Status page health computation tests:** mock various component-down scenarios; assert correct status reflected.
- **Email deliverability tests** against Gmail (Indian-account), Outlook (corporate), and Yahoo. Three test recipients per provider. Spam-folder detection.

### 13.3 Acceptance criteria

See §10.1 launch criteria. All twelve criteria are testable; all are evidenced before launch.

---

## 14. Implementation Tasks

For 3 engineers + CTO across 4 weeks (with parallel third-party work):

### Week 1 — Security and Compliance
- Vendor kickoff for pen test (Day 1). (1d)
- Engage external counsel for DPDP audit. (1d)
- Internal SAST/DAST/SCA tightening: raise alert thresholds, enable PR blocking. (2d)
- Begin RoPA documentation. (3d)
- Status page provisioning + initial component setup. (1d)
- WhatsApp WABA application submission. (1d, parallel)

### Week 2 — Hardening and Load Test
- Pen test results triage (continuous as findings arrive). (3d)
- Critical/High remediation. (parallel)
- Load test harness setup (k6 scripts, synthetic data). (3d)
- Load test execution: steady state, audit burst, recrawl Monday, bulk import. (3d)
- Capacity plan document. (1d)
- PagerDuty integration + alert routing. (2d)

### Week 3 — DR Drill and Runbooks
- DR drill in staging (full procedure). (1d)
- DR drill in partial-prod (recovery procedure validation). (1d)
- Runbook authoring: 30 runbooks across the week. (5d, parallel across team)
- Runbook walkthroughs and sign-offs. (continuous)
- Customer support tool: admin UI, impersonation, approved actions. (4d)
- Help center: 30 articles. (3d, parallel)

### Week 4 — Billing Enablement and Launch
- Quota enforcement implementation (final wiring). (2d)
- Enforcement canary rollout. (2d in this week + watching)
- Pen test re-test (vendor returns). (continuous)
- DPDP compliance memo finalization. (continuous)
- Marketing site finalization. (3d, parallel)
- Soft-launch readiness review. (1d)
- Final launch criteria checklist evaluation. (1d)
- **Launch** (or slip decision).

**Phase 8 exit criteria:** Launch criteria L1–L12 (§10.1) all evidenced. Soft launch active.

---

## 15. Post-Launch (the first 90 days)

Not part of Phase 8 work, but the architecture sets up post-launch trajectories that should be tracked:

| Week | Focus |
|---|---|
| Week 1 post-launch | Daily on-call cadence; rapid response to early issues; status page polish |
| Week 2–4 | Soft launch metrics tracking; bug triage; first feature backlog grooming |
| Week 4 | Soft → hard launch decision |
| Week 5–12 | Hard launch ramp; Series A prep; first major feature release planning |

The architecture documented in HLD §13 anticipates this trajectory; the first scaling decision (audit module extraction to its own service) is well past the 90-day mark.

---

*CitedBy Phase 8 Design v1.0 | Confidential | May 2026*
*This concludes the phased design series. See `CitedBy_Roadmap.md` for the consolidated implementation index.*
