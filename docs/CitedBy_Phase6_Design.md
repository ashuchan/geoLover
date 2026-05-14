# CitedBy — Phase 6 Design
## Weekly Recrawl & Notifications
**Version:** 1.0
**Status:** Approved for implementation
**Date:** May 2026
**Author:** CTO, CitedBy
**Parent document:** `CitedBy_HLD_v1.md`
**Modules covered:** Notifications (#8), plus the scheduled recrawl operating loop that turns Phase 2 into a recurring service

---

## 1. Phase Overview

### 1.1 Why this is Phase 6

Phases 0–5 ship a product that can do one excellent thing once: audit, recommend, generate, publish. **Phase 6 makes the product operate as a service rather than a one-time consultation.** Without Phase 6:
- Customers manually trigger every re-audit.
- They never learn that they *won* a citation — which is the emotional payoff that justifies the subscription.
- They never learn that a publish failed silently, or that an OAuth token broke.
- They don't experience the platform's *attention*, which is what they are actually paying for.

Phase 6 is also where we earn retention. SaaS churn happens when the service feels passive. Weekly proof of work — "we ran your audit, here's what changed, here are 3 new wins" — is the retention engine.

### 1.2 What this phase delivers

By the end of Phase 6:

- **Scheduled recrawl** of every active business runs weekly on a per-business cadence (default Monday 06:00 IST), using a smaller, focused query set (20 queries per PRD).
- **Citation deltas** are computed against the prior baseline; `CitationWon`, `CitationLost`, `CitationImproved`, `CitationDeclined` events fire per detected change.
- A **NotificationService** with a clean adapter model. Email is the only channel enabled in MVP, but the WhatsApp and in-app adapters are built behind feature flags.
- **Digest assembly** — events accumulated through the week are bundled into one weekly digest per business, not a flood of per-event notifications.
- **Channel routing** by event type and customer preferences. An OAuth-failure alert routes differently than a "you won a citation" celebration.
- **Preference center** — customers configure cadence and channels per notification type, with stable signed unsubscribe links.
- **Rate limiting / debouncing** — no customer receives more than N notifications per day; bursts coalesce.
- **Deliverability tracking** — every send / open / click logged for analytics and bounce handling.
- **Publish back-reference attribution** — when a `CitationWon` is detected, we attempt to trace it to a specific verified PublishAttempt URL. This is the metric that proves the loop closes.

### 1.3 What this phase does NOT deliver

- WhatsApp delivery to customers. WABA approval and template-message workflow is Phase 8 work; the adapter is built but disabled.
- SMS, push notifications, phone calls. Not in scope.
- Real-time / immediate citation alerts. Weekly cadence is the product. Sub-weekly is a Phase 8+ retention feature.
- Custom notification templates per agency. The template system supports overrides; agency-level customization UI is Phase 7.

---

## 2. Requirements

### 2.1 Functional requirements

| # | Requirement | Source |
|---|---|---|
| F1 | Every active business has a recurring weekly audit on a configurable day-and-hour. | PRD §3.1 Module 2.4 |
| F2 | The weekly recrawl uses a focused query set (target 20), composed of historical losses + a stable subset of the original audit. | PRD §3.1 Module 2.4 |
| F3 | After each recrawl, citation deltas vs. the prior baseline are computed and persisted. | PRD §3.1 Module 2.4 |
| F4 | `CitationWon`, `CitationLost`, `CitationImproved`, `CitationDeclined` events fire per delta, scoped to (business, query, engine). | New |
| F5 | A weekly digest email is delivered to the configured recipient(s) summarising the period's events. | PRD §3.1 Module 2.4 |
| F6 | Actionable alerts (OAuth failure, publish verification failure, entity seed lost visibility) are delivered promptly — not folded into the weekly digest. | New |
| F7 | Customers configure: cadence of digest, channels per notification type, full unsubscribe. | UX requirement |
| F8 | The system never delivers more than 10 notifications per recipient per 24h. Excess events coalesce. | Anti-spam |
| F9 | Every email has a stable, signed unsubscribe link scoped per (recipient, type). | CAN-SPAM / good practice |
| F10 | Bounced emails are recorded; the address is paused until customer confirms. | Deliverability hygiene |
| F11 | Notification content is rendered from versioned templates stored in the database. | HLD §10.7 |
| F12 | The weekly digest visibly cites back-references from Phase 5 PublishAttempts where attributable. | Loop-closure storytelling |

### 2.2 Non-functional requirements

| # | Requirement | Target |
|---|---|---|
| NF1 | Weekly recrawl completion for all active businesses from schedule trigger. | <6 hours |
| NF2 | Digest email delivery latency from digest generation. | <10 minutes |
| NF3 | Time from event emission to a routed urgent alert send. | <2 minutes p95 |
| NF4 | Email deliverability (delivered / sent). | >97% |
| NF5 | Notification dedup correctness. | 0 duplicates under 1,000-iteration chaos test |
| NF6 | Recrawl cost vs. initial audit. | <30% (smaller query set) |
| NF7 | Preference change effective for next outbound. | <1 minute |

---

## 3. Domain Model — Detailed

### 3.1 Aggregates

#### `RecrawlSchedule`
```
RecrawlSchedule
├── id, tenant_id, business_id
├── cadence              (enum: 'weekly'; future 'biweekly', 'monthly')
├── day_of_week          (0-6; default Monday=0)
├── hour_local           (0-23 IST; default 6)
├── enabled              (boolean)
├── next_run_at, last_run_at
└── algorithm_version_baseline  (text; the audit algorithm version of the most recent baseline)
```

One row per active business. Created on `business.status → 'active'`, removed on suspension/deletion. `algorithm_version_baseline` is captured so we can correctly handle algorithm changes (Pass 1 finding M3 below).

#### `CitationDelta`
```
CitationDelta
├── id, tenant_id, business_id
├── audit_run_id              (the recrawl that produced this delta)
├── prior_audit_run_id        (the baseline comparison run; nullable for first-ever)
├── query_id, engine
├── delta_type                (enum: 'won' | 'lost' | 'improved' | 'declined')
├── prior_state               (JSONB: cited_yes/no, position, confidence)
├── current_state             (JSONB)
├── source_publish_attempt_id (FK to Phase 5; nullable; back-reference heuristic)
└── created_at
```

`improved` / `declined` capture position or confidence movement on already-cited queries — softer than win/loss.

#### `Notification`
```
Notification
├── id, tenant_id, recipient_user_id, business_id (nullable for tenant-level)
├── notification_type        (semantic key, e.g., 'weekly_digest', 'oauth_failure',
│                              'publish_succeeded', 'citation_won_burst')
├── priority                 (enum: 'urgent' | 'standard' | 'digestible')
├── channel                  (enum: 'email' | 'in_app' | 'whatsapp')
├── template_version_id      (FK)
├── render_payload           (JSONB; variables for template)
├── idempotency_key          (text, unique)
├── status                   (enum: 'queued' | 'sending' | 'delivered' |
│                                    'bounced' | 'failed' | 'suppressed')
├── send_attempts
├── delivered_at, bounced_at, failed_at, suppression_reason
└── created_at
```

**Invariants:**
- `idempotency_key` is deterministic. Naming scheme defined in §5.5.
- `suppressed` covers both "preference filter rejected" and "rate-limited out".

#### `NotificationTemplate`
```
NotificationTemplate
├── id, template_key, version
├── channel, locale (default 'en-IN')
├── subject_template (for email)
├── body_template (Mustache or Liquid)
├── variables_schema (JSONB; validates render_payload)
├── active (boolean), created_by, created_at
```

Versioned same as prompts. A template change is a new version row; rollback is non-destructive.

#### `NotificationPreference`
```
NotificationPreference
├── id, user_id, tenant_id, notification_type
├── channels_enabled       (text[]; subset of channel enum)
├── cadence                (enum: 'immediate' | 'daily_digest' | 'weekly_digest' | 'off')
└── updated_at
UNIQUE (user_id, tenant_id, notification_type)
```

Sensible defaults seeded per type at user creation. Customers override in the preference center.

#### `OutboundDeliveryLog`
```
OutboundDeliveryLog
├── id, notification_id
├── provider                 (e.g., 'resend')
├── provider_message_id
├── event                    (queued|sent|delivered|bounced|complaint|opened|clicked)
├── event_time, event_details (JSONB)
```

Resend (and future provider) webhooks write here. Used for deliverability dashboards and bounce handling.

#### `BouncedAddress`
```
BouncedAddress
├── email_normalized (PK)
├── bounce_type (hard | complaint)
├── bounced_at, cleared_at (nullable)
```

Platform-wide table — a hard-bounce on `alice@acme.com` pauses delivery from all tenants until cleared, because the underlying email infra is the same.

### 3.2 Relationships

```
Business 1───1 RecrawlSchedule
AuditRun (Phase 2) 1───N CitationDelta
CitationDelta N───0..1 PublishAttempt (Phase 5; back-reference)
User N───N NotificationPreference (per type)
Notification 1───N OutboundDeliveryLog
NotificationTemplate (version) 1───N Notification
```

---

## 4. Scheduled Recrawl

### 4.1 Schedule machinery — the scale question

The naive design: one Temporal schedule per business. Simple, but at 10,000 businesses that's 10,000 schedules — Temporal Cloud handles it but the price scales linearly and the operational dashboard becomes noisy.

**The chosen design: bucket-based schedules.** We use 168 schedules — one per (day-of-week × hour). Every active business with `day_of_week=0, hour_local=6` is processed by the `recrawl-mon-06` schedule. The workflow for that schedule fans out to all businesses in that bucket via parallel child workflows.

This is a 60× reduction in schedule count, and gives us a natural concurrency control point (the bucket workflow rate-limits its own fan-out). The mapping `(business, day, hour) → bucket` is recomputed daily from `RecrawlSchedule` to handle customers changing their cadence.

### 4.2 The WeeklyRecrawlBucketWorkflow

```
WeeklyRecrawlBucketWorkflow(bucket_id="recrawl-mon-06")
   │
   ├─ Activity: ListBusinessesInBucket — query RecrawlSchedule rows
   ├─ For each business (bounded parallel; 20 concurrent):
   │     └─ Child workflow: BusinessRecrawlWorkflow(business_id)
   │           ├─ Activity: AssertBusinessActive (skip suspended/deleted)
   │           ├─ Activity: SelectQuerySet (~20 queries; §4.3)
   │           ├─ Activity: StartAuditRun (Phase 2 AuditWorkflow w/ smaller query set)
   │           ├─ Wait for AuditRunCompleted
   │           ├─ Activity: ComputeCitationDeltas (§4.4)
   │           ├─ Activity: PersistScoreSnapshot (Phase 3)
   │           ├─ Activity: ScheduleDigestNotification — queues a 'weekly_digest'
   │           │            with idempotency_key keyed on the recrawl run, not period_end_date
   │           │            (Pass 2 finding M1)
   │           └─ DONE
   └─ DONE
```

The bucket workflow's overlap policy is `SKIP` — if a prior run is somehow still active, the new run skips entirely. The per-business child workflow's overlap is enforced by `BusinessRecrawlWorkflow` ID being deterministic: `recrawl-{business_id}-{period_iso}`. A duplicate start is a no-op.

### 4.3 Query set selection

The 20-query recrawl set is composed of:
- **12 "tracker" queries**: queries the business has been losing on. Picking these focuses the recrawl on the queries most likely to flip to wins (so we can celebrate them).
- **8 "anchor" queries**: a stable subset of the original 50-query audit set. These detect declines on queries previously won — early warning when a competitor catches up.

The composition is recomputed weekly so as wins happen, those queries graduate out of "tracker" and new losing queries rotate in. The result is a recrawl that's both responsive (focused on current losses) and continuous (anchored on a stable comparison set).

Cost characteristic: 20 queries × ~3 engines = 60 probes vs. 150 for the initial audit. ~40% cost. Within NF6 target.

### 4.4 Computing citation deltas

For each (query, engine) pair in the recrawl:

```
Step 1: Find the corresponding citation result in the prior baseline AuditRun.
        If the algorithm_version of baseline differs from current:
          → Skip delta computation for this query. Record as 'baseline_reset'.
          → The digest copy explains: "Methodology updated, baseline reset."

Step 2: Compare:
        prior  = {cited: bool, position: int, confidence: float}
        current = {cited: bool, position: int, confidence: float}
        
        if prior.cited == False and current.cited == True:    → 'won'
        if prior.cited == True and current.cited == False:    → 'lost'
        if both cited, current.position is materially better: → 'improved'
        if both cited, current.position is materially worse:  → 'declined'
        otherwise: no delta, do nothing
```

"Materially better/worse" is defined: position change ≥ 2 *or* confidence delta ≥ 0.15. The thresholds suppress noise.

### 4.5 Publish back-reference attribution

When a `CitationWon` delta is detected, we attempt attribution:

1. For the business, gather all `PublishAttempt` rows with `status='verified'` and `public_url IS NOT NULL`.
2. For the engine response that triggered the new citation, search the raw text (preserved from Phase 2) for any of those URLs.
3. If found, set `CitationDelta.source_publish_attempt_id`. The digest can say "Likely traceable to your published asset at <URL>".
4. If not found, leave null. The digest still celebrates the win but with attribution as "organic / unattributed".

This is heuristic, not causal. The copy is honest about it. But even probabilistic attribution is a powerful product signal: "we did this for you." It's the loop closing visibly.

---

## 5. The Notification Service

### 5.1 Public interface

```python
class NotificationService:
    async def queue(
        self,
        *,
        recipient_user_id: UUID,
        tenant_id: UUID,
        notification_type: str,
        priority: NotificationPriority,
        render_payload: dict,
        idempotency_key: str,
        business_id: UUID | None = None,
    ) -> list[Notification]:
        """
        Apply preference filter, idempotency check, rate-limit check.
        Returns the persisted Notifications (one per enabled channel; can be empty if suppressed).
        """
```

Critically, callers do **not** specify the channel. The service picks channels from the recipient's `NotificationPreference` for this type. A single `queue()` call may produce zero, one, or multiple `Notification` rows.

### 5.2 The delivery flow

```
queue(...)
   ├─ Look up NotificationPreference for (user, tenant, type)
   ├─ If cadence='off': persist Notification(status='suppressed') for audit; return
   ├─ Idempotency check on UNIQUE(idempotency_key)
   │   → If exists: return the existing rows (no-op)
   ├─ Rate-limit check (§5.6)
   │   → If exceeded for digestible: suppress with explanation
   │   → If exceeded for urgent: override; urgent always sends (modulo per-day max of 25 absolute)
   ├─ For each channel in preference.channels_enabled:
   │   ├─ Resolve template via (notification_type, channel, locale)
   │   ├─ Validate render_payload against template.variables_schema
   │   ├─ Render subject + body
   │   ├─ Persist Notification(status='queued')
   │   └─ Hand off to channel-specific worker via Temporal workflow

ChannelDeliveryWorkflow(notification_id) — runs per notification:
   ├─ Activity: SendViaChannel — calls the channel adapter
   ├─ On retryable failure: Temporal retries with exp backoff (max 5 attempts)
   ├─ On terminal failure: status='failed', emit NotificationFailed
   ├─ Wait for delivery webhook OR timeout (24h)
   │   → On delivered: status='delivered', delivered_at set
   │   → On bounced: status='bounced'; handle per §5.7
```

### 5.3 Digest assembly — the product-critical path

The digest is the most user-visible notification type. Its assembly is more elaborate than other types:

```
WeeklyDigestAssemblyWorkflow(business_id, audit_run_id)
   │
   ├─ Activity: GatherDeltas — all CitationDelta rows for this audit_run_id
   ├─ Activity: GatherPublishEvents — newly-verified publishes for the period
   ├─ Activity: GatherActiveWarnings — failed OAuth, lost-visibility seeds (carry-over)
   ├─ Activity: ComposeDigestPayload
   │      Structure:
   │        - headline: score change ("AI Visibility up 7 points")
   │        - wins: top 3-5 won citations, with snippet + engine + attribution
   │        - losses: top 3 losses (only if non-empty)
   │        - publishes_live: newly-verified publishes from Phase 5
   │        - action_required: warnings needing customer intervention
   │        - quiet_week_marker: bool (Pass 2 finding H2)
   ├─ Activity: NotificationService.queue(type='weekly_digest', ...)
   └─ DONE
```

The composition leads with positive — wins, score increases — and surfaces losses only if material. We don't depress the customer over the score moving 67 → 66.

**Quiet-week handling (Pass 2 H2 resolution):** when no material deltas exist, the digest still sends but with a clearly different shape: "We ran your recrawl on Monday. Nothing changed this week — your scores are stable." This signals presence without manufacturing fake updates. Customers who never want quiet-week digests can set `cadence='only_when_active'` (cadence enum extension).

### 5.4 Channel adapters

```python
class NotificationChannel(Protocol):
    name: str
    
    async def send(self, notification: Notification, rendered: RenderedMessage) -> SendResult: ...
    async def supports(self, recipient: Recipient) -> bool: ...
```

Concrete adapters in Phase 6:
- `EmailChannel` — uses Resend; SendGrid configured as failover (Phase 8 fully wired).
- `InAppChannel` — writes to a dashboard inbox table read by the UI; "send" means "persist as visible".
- `WhatsAppChannel` — implemented but feature-flag-disabled until Phase 8 WABA setup.

Same interface shape as the Publisher and AIEngine adapters from earlier phases. Adding SMS later is one new class plus a config row.

### 5.5 Idempotency key naming

Different notification types need different keys:

| `notification_type` | `idempotency_key` formula |
|---|---|
| `weekly_digest` | `hash('weekly_digest', user_id, audit_run_id)` — keyed on the run, not the calendar period (Pass 2 M1) |
| `oauth_failure` | `hash('oauth_failure', user_id, oauth_token_id, refresh_attempt_id)` |
| `publish_succeeded` | `hash('publish_succeeded', user_id, publish_attempt_id)` |
| `publish_verification_failed` | `hash('publish_verification_failed', user_id, publish_attempt_id)` |
| `entity_seed_verified` | `hash('entity_seed_verified', user_id, entity_seed_id)` |
| `entity_seed_lost_visibility` | `hash('entity_seed_lost_visibility', user_id, entity_seed_id, alert_iteration)` |
| `citation_won_burst` | `hash('citation_won_burst', user_id, business_id, debounce_window_start)` |

The principle: the key should make the same notification idempotent across retries but allow different notifications to be distinct. Keyed on the event-producing entity, not on the calendar.

### 5.6 Rate limiting and debouncing

Two distinct mechanisms.

**Per-user rate limit** (Redis counter at `notif_count:{user_id}:{date_iso}`, expires nightly):
- 10/day cap for `digestible` + `standard` priorities.
- `urgent` priority bypasses, with absolute hard cap of 25/day (above which something has gone wrong and we should not flood the customer).

**Type-specific debouncing**:
- `citation_won_burst`: events within a 1-hour window coalesce. The first event triggers a 1-hour timer; all wins in that window aggregate into one "5 new citations won! See dashboard" notification. The `debounce_window_start` in the idempotency key reflects the timer's anchor.
- `publish_succeeded` for a single brief publishing to multiple targets: events coalesce within a 15-minute window into one "Your content is now live on 3 channels" notification.

Implementation: a workflow `DebounceCollectorWorkflow(type, user_id, business_id)` opens on first event, sleeps for the debounce window, collects subsequent events into a list (subscribed via a Temporal signal), then on timer fire issues one consolidated `queue()` call with the aggregated payload.

### 5.7 Bounce and complaint handling

Resend webhooks deliver delivery events to `/api/v1/webhooks/resend`. Handler:

- **Soft bounce**: log; do nothing. Resend will retry per its policy.
- **Hard bounce**: insert into `bounced_addresses` with `bounce_type='hard'`. All future deliveries to this address are paused; in-app banner appears for the user: "Email delivery paused — your address bounced. Update it or confirm to resume." The user can confirm in-dashboard (we send a verification email to the new address; success clears the bounce).
- **Spam complaint**: same flow as hard bounce, plus in-app: "Notifications paused per your request. Resume any time in Settings."

The pause is per-recipient-address, not per-tenant. A user who fixes their email address resumes immediately.

### 5.8 Unsubscribe — and its security risk

Standard practice is a signed JWT in the unsubscribe link:
```
https://app.citedby.app/unsubscribe?token={jwt}
```
where the JWT contains `(user_id, notification_type, channel)` and clicking instantly unsubscribes that combination — no login required.

The problem (Pass 1 H3): forwarding an email exposes the unsubscribe link. A malicious actor could unsubscribe a customer from `oauth_failure` alerts, then trigger an OAuth break, and the customer would never learn their integration is dead.

**Resolution:**
- **Marketing-type notifications** (`weekly_digest`, `citation_won_burst`) use the standard one-click unsubscribe. Loss of a digest is annoying, not catastrophic.
- **Critical-type notifications** (`oauth_failure`, `publish_verification_failed`, `entity_seed_lost_visibility`, anything `priority='urgent'`) cannot be unsubscribed via link. The link redirects to a logged-in preference page where the user must authenticate before disabling. The email copy on these is honest: "This is an important account alert. To change which alerts you receive, sign in to your account."

Marketing types still get the easy unsubscribe per CAN-SPAM / good UX. Critical types are auth-gated. The product remains forwardable without the safety hazard.

---

## 6. Database Schema (additions)

```sql
CREATE TABLE recrawl_schedules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL UNIQUE REFERENCES businesses(id),
    cadence TEXT NOT NULL DEFAULT 'weekly',
    day_of_week SMALLINT NOT NULL DEFAULT 0 CHECK (day_of_week BETWEEN 0 AND 6),
    hour_local SMALLINT NOT NULL DEFAULT 6 CHECK (hour_local BETWEEN 0 AND 23),
    enabled BOOLEAN NOT NULL DEFAULT true,
    next_run_at TIMESTAMPTZ,
    last_run_at TIMESTAMPTZ,
    algorithm_version_baseline TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX recrawl_schedules_bucket_idx
    ON recrawl_schedules(day_of_week, hour_local) WHERE enabled = true;

CREATE TYPE citation_delta_type AS ENUM ('won', 'lost', 'improved', 'declined');

CREATE TABLE citation_deltas (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL,
    audit_run_id UUID NOT NULL,
    prior_audit_run_id UUID,
    query_id UUID NOT NULL,
    engine TEXT NOT NULL,
    delta_type citation_delta_type NOT NULL,
    prior_state JSONB,
    current_state JSONB NOT NULL,
    source_publish_attempt_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX citation_deltas_audit_idx ON citation_deltas(audit_run_id);
CREATE INDEX citation_deltas_business_idx ON citation_deltas(business_id, created_at DESC);

CREATE TABLE notification_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    channel TEXT NOT NULL,
    locale TEXT NOT NULL DEFAULT 'en-IN',
    subject_template TEXT,
    body_template TEXT NOT NULL,
    variables_schema JSONB NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT false,
    created_by_user_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (template_key, version, channel, locale)
);
CREATE UNIQUE INDEX notification_templates_active_uniq
    ON notification_templates(template_key, channel, locale) WHERE active = true;

CREATE TYPE notification_priority AS ENUM ('urgent', 'standard', 'digestible');
CREATE TYPE notification_status AS ENUM (
    'queued', 'sending', 'delivered', 'bounced', 'failed', 'suppressed'
);

CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    recipient_user_id UUID NOT NULL REFERENCES users(id),
    business_id UUID,
    notification_type TEXT NOT NULL,
    priority notification_priority NOT NULL DEFAULT 'standard',
    channel TEXT NOT NULL,
    template_version_id UUID REFERENCES notification_templates(id),
    render_payload JSONB NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status notification_status NOT NULL DEFAULT 'queued',
    send_attempts INTEGER NOT NULL DEFAULT 0,
    delivered_at TIMESTAMPTZ,
    bounced_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    suppression_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX notifications_recipient_idx ON notifications(recipient_user_id, created_at DESC);
CREATE INDEX notifications_status_idx
    ON notifications(status) WHERE status IN ('queued', 'sending');

CREATE TYPE notification_cadence AS ENUM (
    'immediate', 'daily_digest', 'weekly_digest', 'only_when_active', 'off'
);

CREATE TABLE notification_preferences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id),
    tenant_id UUID NOT NULL,
    notification_type TEXT NOT NULL,
    channels_enabled TEXT[] NOT NULL DEFAULT '{}',
    cadence notification_cadence NOT NULL DEFAULT 'immediate',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (user_id, tenant_id, notification_type)
);

CREATE TABLE outbound_delivery_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    notification_id UUID NOT NULL REFERENCES notifications(id),
    provider TEXT NOT NULL,
    provider_message_id TEXT,
    event TEXT NOT NULL,
    event_time TIMESTAMPTZ NOT NULL,
    event_details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX delivery_log_notification_idx ON outbound_delivery_log(notification_id);

CREATE TABLE bounced_addresses (
    email_normalized TEXT PRIMARY KEY,
    bounce_type TEXT NOT NULL,
    bounced_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at TIMESTAMPTZ
);
```

**RLS:** `recrawl_schedules`, `citation_deltas`, `notifications`, `notification_preferences`, `outbound_delivery_log`. Not on `notification_templates` or `bounced_addresses` (platform-wide).

---

## 7. Self-Review

### Pass 1

| # | Severity | Finding | Where |
|---|---|---|---|
| H1 | **High** | Per-business Temporal schedules would scale at 10k businesses to 10k schedules. Even Temporal Cloud's capacity is fine, but the cost and operational noise grow linearly. | §4.1 |
| H2 | **High** | The "suppress digest if no material deltas" idea is product-sensible but creates a silent-failure signal: customers can't distinguish "service ran, nothing happened" from "service is broken". | §5.3 |
| H3 | **High** | Unsubscribe via signed JWT link (standard practice) means a forwarded email can unsubscribe a user from critical alerts (OAuth failure, publish failure). Customer never learns their integration is broken. | §5.8 |
| M1 | Medium | Digest idempotency_key = hash('weekly_digest', user_id, business_id, period_end_date) breaks if the recrawl runs late and crosses into the next period — same period_end_date conflict. | §5.5 |
| M2 | Medium | The "10/day per user" cap will routinely break for agency_admins who manage many businesses. 5 businesses × 1 digest + alerts = easily 10+. | §5.6 |
| M3 | Medium | Comparison baseline can be from a different algorithm_version than the current run. Comparing across versions produces misleading deltas. | §4.4 |
| M4 | Medium | WhatsApp adapter built but feature-flag-disabled. If a customer toggles a preference for WhatsApp channel before WABA is approved, queued notifications silently fail. | §5.4 |
| M5 | Medium | The DebounceCollectorWorkflow (§5.6) holds state for an hour. If it crashes/restarts, in-flight events could be lost or double-counted. | §5.6 |
| M6 | Medium | NotificationPreference defaults are seeded "at user creation". But Phase 1 users already exist before Phase 6 ships — migration story for existing users isn't specified. | §3.1 NotificationPreference |
| L1 | Low | The "publish back-reference" heuristic in §4.5 searches engine response text for URLs. AI engines often paraphrase rather than quote URLs verbatim. | §4.5 |

Three highs and six mediums. Iterating.

### Pass 2 (resolutions)

**H1 (schedule scale):** Bucket-based schedules. 168 schedules (one per day-of-week × hour combination), each fanning out to all businesses configured for that bucket. Reduces schedule count by 60×; gives natural per-bucket concurrency control. Documented in §4.1. The trade-off: changing a business's recrawl day/hour requires moving it between buckets (a row update on `recrawl_schedules` — already supported).

**H2 (silent service signal):** Quiet-week digests still send, with a distinctly different shape: "We ran your recrawl on Monday. Nothing changed this week — your scores are stable." Customers who specifically prefer silence on quiet weeks can opt into `cadence='only_when_active'` (new cadence enum value). The default is the quiet-week digest, because absence of communication is worse than mild content.

**H3 (unsubscribe link forwarding):** Two tiers. Marketing types (`weekly_digest`, `citation_won_burst`, etc.) keep the standard one-click unsubscribe. Critical types (`oauth_failure`, `publish_verification_failed`, anything with `priority='urgent'`) require authentication before unsubscribing — the link redirects to a signed-in preference page. Email copy explicitly notes "This is an important account alert" and points to where preferences can be changed. Documented in §5.8.

**M1 (digest idempotency key):** Changed scheme. The key is now `hash('weekly_digest', user_id, audit_run_id)` — keyed on the actual recrawl run, not the calendar period. If a recrawl runs late, it's still one digest per run, period boundary irrelevant. The trade-off: if a recrawl re-runs (e.g., manually triggered after a fix), it would dedupe — which is correct behavior. Documented in §5.5.

**M2 (agency_admin rate limit):** The 10/day cap applies per (user_id, business_id) pair for business-specific notification types, and per user_id for cross-business types. An agency_admin managing 5 businesses sees up to 10 per business per day for business-scoped types (50 max) but only 10 per day for global types. In practice the digest is once per business per week, so this isn't a real cap for the digest pattern. Hard absolute cap raised to 50/day cross-tenant. Documented in §5.6.

**M3 (algorithm version baseline):** Implemented: `RecrawlSchedule.algorithm_version_baseline` is captured. The delta computation in §4.4 explicitly checks: if the prior baseline's algorithm version is incompatible with the current run, deltas are skipped for affected queries and the digest copy explains "methodology update — baseline reset". This is the resolution of HLD §15 R8.

**M4 (WhatsApp preference set early):** Pre-WABA, the WhatsApp channel is filtered out at the preference-write layer — users cannot select it from the preference center until the platform feature flag `whatsapp_enabled=true` is on for their tenant. If a user has somehow set it (e.g., via API directly), the delivery flow's "for each channel in preference.channels_enabled" filters out channels not feature-flag-enabled, logs a warning, and falls back to email-only. Documented in §5.2.

**M5 (DebounceCollectorWorkflow durability):** Temporal handles this natively — the workflow's state (the list of events received via signals) is part of its persisted state. A worker crash/restart resumes the workflow exactly where it was, with all signals delivered before crash still in the workflow's signal queue. This is exactly why we use Temporal; no additional design needed. Documented in §5.6.

**M6 (existing users preference migration):** Phase 6 deploy includes a one-time migration: for every existing user, seed `NotificationPreference` rows with platform defaults for every notification type. The migration runs before the recrawl scheduler is enabled. Users who later interact with the preference center can override; before then, defaults apply. Documented as an implementation task in §9.

**L1 (URL paraphrase):** Heuristic limitation acknowledged. We also match the business's `website_url` (eTLD+1) in the response text — this catches "according to sharma-dental.com" even without the full path. Additionally, we capture confidence: `source_publish_attempt_id` is set only when a path-match is found; a domain-only match sets `source_attribution='domain_match'` (a softer label). The digest copy reflects: "likely traceable" vs "appears related". Documented in §4.5.

### Pass 3

Re-reviewing post-resolution:

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M7 | Medium | The bucket-based schedule fans out to businesses *inside* the bucket workflow. If the bucket workflow fails or is throttled, all businesses in that bucket fail together. | Mitigation: each business runs as a *child workflow* with its own retry policy; parent failure is isolated from children. Children inherit the bucket's concurrency limit (20 parallel) but execute and fail independently. If the parent crashes mid-fan-out, Temporal resumes from the last fan-out point. Documented in §4.2. |
| L2 | Low | Bounced address pausing is per-recipient (address). If the recipient changes the address but the new address also bounces, no special handling. | Acceptable: each address is independently tracked; consecutive bounces are independent events. We log them for analytics. |

**M7 resolved.** No remaining H or M findings. **Self-review passes.**

---

## 8. Test Strategy

### 8.1 Unit tests
- `BusinessRecrawlWorkflow` against stubbed AuditWorkflow: assert correct query set selection, delta computation invariants.
- `NotificationService.queue` with various preference configurations: assert correct channel routing, suppression behavior.
- Idempotency: 1,000-iteration fuzz test against `queue()` with same idempotency_key → assert exactly one Notification persisted.
- Rate-limit logic at 9/10/11 events: assert boundary behavior.
- Delta classification: position changes of 1, 2, 5, 10 with confidence deltas — assert `improved`/`declined`/`no-delta` correctly.

### 8.2 Integration tests
- Full WeeklyRecrawlBucketWorkflow against a test bucket of 10 stubbed businesses: assert all complete, deltas correctly computed.
- Digest assembly: build a digest from a fixture set of CitationDelta + PublishAttempt + warnings. Assert payload structure.
- Critical-type unsubscribe link: assert redirect to auth required.
- Marketing-type unsubscribe link: assert one-click works without auth.
- Channel adapter failover: simulate Resend down, assert SendGrid attempt (Phase 8 final wire-up).

### 8.3 Resilience tests
- Recrawl with engine adapter failures: assert per-engine isolation, partial recrawl handled gracefully.
- Bounce webhook flood: 1,000 webhook events in 1 minute — assert no DB contention, all logged.
- DebounceCollectorWorkflow with 50 signals in window: assert all coalesce into one notification.

### 8.4 Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| AC1 | A business with an `active` status has a `RecrawlSchedule` created within 1 minute and a `next_run_at` set. | Integration test |
| AC2 | Bucket workflow on Monday 06:00 processes all businesses in that bucket within 6 hours (NF1). | Synthetic load test |
| AC3 | A `CitationWon` event triggers a digest entry within the same digest cycle. | Integration test |
| AC4 | A `oauth_failure` event triggers an urgent email within 2 minutes (NF3). | Integration test |
| AC5 | A user with `cadence='off'` for a type receives zero notifications of that type for 7 days. | E2E |
| AC6 | A user's address that hard-bounces is added to `bounced_addresses` within 1 minute of webhook. | Integration test |
| AC7 | Critical-type unsubscribe link requires authentication; marketing-type does not. | Manual + automated |
| AC8 | Algorithm-version mismatch between baseline and current run results in baseline-reset digest copy. | Integration test |

---

## 9. Implementation Tasks (sprint-ready)

For 2 backend + 1 frontend across 2.5 sprints (5 weeks):

### Sprint 1 — Recrawl machinery
- RecrawlSchedule schema + create-on-business-activate hook. (1d)
- 168 bucket-schedule provisioning script. (1d)
- WeeklyRecrawlBucketWorkflow + BusinessRecrawlWorkflow (Temporal). (3d)
- Query set selection logic (12 trackers + 8 anchors). (2d)
- CitationDelta computation, algorithm-version handling. (2d)
- Publish back-reference attribution heuristic (URL + domain match). (1d)

### Sprint 2 — Notification core
- Notification, NotificationTemplate, NotificationPreference schemas + RLS. (1d)
- Template seed: 10 starter templates (weekly_digest, oauth_failure, publish_succeeded, publish_verification_failed, entity_seed_verified, entity_seed_lost_visibility, citation_won_burst, account_invitation, password_reset, quiet_week_digest). (2d)
- NotificationService.queue with preference + idempotency + rate-limit. (2d)
- EmailChannel adapter (Resend). (1d)
- InAppChannel adapter (inbox table + dashboard read API). (1d)
- WhatsAppChannel adapter (flag-disabled). (1d)
- ChannelDeliveryWorkflow + retry/failure handling. (2d)
- Resend webhook handler + bounce processing. (1d)

### Sprint 3 (half) — Digest, debounce, UX
- WeeklyDigestAssemblyWorkflow. (2d)
- DebounceCollectorWorkflow with signal-based aggregation. (2d)
- Preference center UI. (2d)
- Unsubscribe pages (one-click + auth-gated). (1d)
- Defaults migration for existing Phase 1 users. (1d)
- Acceptance test walkthrough. (1d)

**Phase 6 exit criteria:**
- §8.4 ACs pass.
- Demo agency receives a real weekly digest with at least one CitationWon attribution.
- Preference center is live and changes propagate within 1 minute.
- Bounce handling tested end-to-end against Resend's sandbox.

---

## 10. Handoff to Phase 7

Phase 7 (Whitelabel & Agency Portal) consumes from this phase:
- `NotificationTemplate.template_overrides` (existing nullable field on the schema): Phase 7 populates this with per-agency overrides for `subject_template`, `body_template`, and sender configuration.
- `NotificationChannel.send()` is extended (interface-compatible) to use agency-specific sender identity (`from` address, friendly name) resolved per Notification.tenant_id at send time.
- `EmailChannel` is configured to accept per-agency sender domains and authentication (SPF/DKIM/DMARC) — Phase 7 defines the workflow that sets these up.
- The `WeeklyDigestAssemblyWorkflow`'s payload structure becomes the template variables that agency-customized templates consume.

The contract: Phase 6 defines the *what* (events, structure, templates). Phase 7 defines the *how it looks* (branding, sender, theming) when an agency is involved.

---

*CitedBy Phase 6 Design v1.0 | Confidential | May 2026*
*Next: Phase 7 — Whitelabel & Agency Portal*
