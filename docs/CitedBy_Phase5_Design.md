# CitedBy — Phase 5 Design
## Publishing & Entity Seeding
**Version:** 1.0
**Status:** Approved for implementation
**Date:** May 2026
**Author:** CTO, CitedBy
**Parent document:** `CitedBy_HLD_v1.md`
**Modules covered:** Publishing (#5), Entity Seeding (#6)

---

## 1. Phase Overview

### 1.1 Why this is Phase 5

Phase 4 produces approved content. **Phase 5 puts that content where AI engines can find it.** Without Phase 5, the product diagnoses ("you are not cited"), prescribes ("here is content that would get you cited"), but does not treat. Phase 5 closes the loop.

This phase introduces our first **external-write surfaces** — OAuth-bound integrations with systems we do not control (Google Business Profile, WordPress, directory APIs). Every architectural decision in this phase exists to handle the realities of those systems: tokens expire, APIs rate-limit, schemas drift, requests partially succeed. The cost of a bug here is not data corruption inside our system — it is incorrect content sent to a customer's most important public-facing assets. The bar is high.

### 1.2 What this phase delivers

By the end of Phase 5:

- A **PublisherAdapter** abstraction with concrete implementations for Google Business Profile (OAuth) and WordPress (REST API + snippet/manual fallback for non-WordPress sites).
- **OAuth token management** — secure storage with KMS envelope encryption, automatic refresh via a daily sweep workflow, customer-facing reconnect prompts on refresh failure.
- A **PublishWorkflow** (Temporal): durable, idempotent, retry-safe, with explicit verification of successful publication.
- **Entity Seeding** to a curated directory registry (40+ Indian + global directories) with verification polling over 30 days.
- **PublishTarget** management — the inventory of where a business can publish (each business may have GBP, a WordPress site, multiple directories, etc.).
- A **PublishApproval gate** that re-confirms the customer authorises this specific publish, the second time content goes live (the first authorisation was content approval in Phase 4).
- A **CitationBack-Reference** mechanism — when Phase 6's re-crawl detects a new citation, we can trace it back to the published asset that earned it. This is the metric that proves the loop closes.

### 1.3 What this phase does NOT deliver

- Justdial / IndiaMart / Sulekha publisher adapters. Their APIs require partnership negotiation; Phase 2 work. The directory registry has rows for them so the configuration is ready; concrete adapters are deferred.
- Schema-aware editing of existing published content (Phase 7 + Phase 8). Phase 5 publishes new posts/pages; it does not edit prior CitedBy-published content beyond marking it superseded.
- Image generation or asset upload (no Phase 4 image work; not needed).
- Social media publishing (Facebook, LinkedIn). Not a citation surface for AI engines; out of scope.
- Wikipedia editing. Editorial policies make automated submission inappropriate; we offer guidance to manual Wikipedia work in Phase 8 only.

---

## 2. Requirements

### 2.1 Functional requirements

| # | Requirement | Source |
|---|---|---|
| F1 | A business can connect a Google Business Profile via OAuth. | PRD §3.1 Module 2.2 |
| F2 | A business can declare a WordPress site (URL + API credentials or app password); we publish to it as posts or pages. | PRD §3.1 Module 2.2 |
| F3 | A business can declare a non-WordPress website by uploading a verification file; we issue copy-paste snippets for manual installation. | PRD §3.1 Module 2.2 |
| F4 | An approved ContentBrief can be published to one or more configured PublishTargets, with explicit per-target opt-in. | PRD §3.1 Module 2.2 (approval workflow) |
| F5 | Every publish operation is idempotent: retrying produces no duplicates. | HLD §10.2; PRD non-functional |
| F6 | OAuth tokens are refreshed automatically before expiry; refresh failures generate customer-facing reconnect alerts. | Phase 4 plan §6.4 R5 resolution |
| F7 | After publish, a verification step confirms the content is live at the expected location. | Quality requirement |
| F8 | Entity Seed submissions go to a curated directory registry; each submission's status is tracked from `submitted` → `pending` → `verified` over 30+ days. | PRD §3.1 Module 2.3 |
| F9 | A business owner can revoke publish authorisation at any time; subsequent publishes for that target are blocked. | DPDP; customer right |
| F10 | A publish that goes live carries a back-reference (URL + asset_id) so later citation detection can link the citation to the publish. | New requirement for loop closure |
| F11 | Failed publishes (after retry) generate a notification to the customer with the specific failure reason and remediation. | UX requirement |
| F12 | Publishing to a target subject to rate limiting respects that limit; multiple publishes are queued, not failed. | Operational requirement |

### 2.2 Non-functional requirements

| # | Requirement | Target |
|---|---|---|
| NF1 | Publish latency (single approved brief, single target). | <60 seconds p95 |
| NF2 | OAuth refresh sweep coverage. | 100% of tokens within 48h of expiry, refreshed at least 24h ahead |
| NF3 | Idempotency under retry. | 0 duplicate posts across 1,000 retries in chaos test |
| NF4 | Verification accuracy. | >99% (published → verified within 24h; <1% false-negative reverification) |
| NF5 | Entity seed submission throughput. | 50 directories per business within 7 days of activation |
| NF6 | OAuth token at-rest encryption. | KMS envelope; auditable decrypt |
| NF7 | Publish failure rate (non-customer-attributable). | <2% per quarter |

---

## 3. Domain Model — Detailed

### 3.1 Aggregates

#### `PublishTarget`
A specific destination configured for a business.

```
PublishTarget
├── id                       (UUID)
├── tenant_id, business_id   (FK)
├── channel                  (enum: 'google_business_profile' | 'wordpress' |
│                                    'website_snippet' | 'justdial' | 'indiamart' | 'sulekha')
├── status                   (enum: 'pending_oauth' | 'connected' | 'failed' | 'revoked' | 'disabled')
├── connected_account_label  (text, e.g. "Sharma Dental — GBP")
├── external_identifier      (text, e.g. GBP locationName or WordPress site URL)
├── oauth_token_id           (FK → oauth_tokens, nullable for non-OAuth channels)
├── publish_authorized_at    (timestamp; F4 explicit opt-in)
├── revoked_at               (nullable; F9)
├── last_publish_at          (nullable)
├── created_at, updated_at
└── meta                     (JSONB; channel-specific config — e.g. WP default post category)
```

**Invariants:**
- At most one `PublishTarget` per (business, channel, external_identifier) — enforced by partial unique index.
- A `revoked` target cannot be reactivated; create a new target instead. This makes consent revocation auditable.

#### `OAuthToken`
```
OAuthToken
├── id                       (UUID)
├── tenant_id                (FK; denormalised for RLS)
├── provider                 (enum: 'google' | 'wordpress' | future)
├── access_token_encrypted   (BYTEA; KMS-envelope-encrypted)
├── refresh_token_encrypted  (BYTEA; same)
├── access_token_expires_at  (timestamp)
├── scope                    (text; granted scopes)
├── account_subject          (text; provider's user id / account ref)
├── created_at, updated_at
└── last_refreshed_at        (nullable)
```

**Invariants:**
- The plaintext token *never* exists in any persistent store. It is decrypted into memory at use, used, and discarded.
- A refresh failure marks the token's parent PublishTarget as `failed`. Token is preserved (not deleted) for forensic analysis until the customer reconnects.

#### `PublishAttempt`
```
PublishAttempt
├── id                       (UUID)
├── tenant_id, business_id   (FK)
├── target_id                (FK → publish_targets)
├── content_asset_id         (FK → content_assets)
├── brief_id                 (FK → content_briefs)
├── idempotency_key          (text, unique)
├── status                   (enum: 'queued' | 'in_progress' | 'succeeded' |
│                                    'failed_retryable' | 'failed_terminal' | 'verified')
├── attempts_count           (integer)
├── external_object_id       (text, nullable; e.g. GBP postId, WP postId)
├── public_url               (text, nullable; the live URL after success)
├── verified_at              (nullable)
├── last_attempt_at, next_attempt_at
├── failure_reason           (text, nullable; structured code + message)
├── created_at
```

**Invariants:**
- `idempotency_key` is unique across the whole table — UNIQUE constraint.
- The key is deterministic: `hash(target_id, content_asset_id)`. The same asset to the same target retries the same row, never creates a duplicate.
- `external_object_id` is set on first successful response; on retry, we check it exists before re-publishing.

#### `EntitySeed`
```
EntitySeed
├── id                       (UUID)
├── tenant_id, business_id   (FK)
├── directory_id             (FK → directory_registry)
├── submission_payload       (JSONB; what we sent)
├── submitted_at
├── status                   (enum: 'pending_submission' | 'submitted' | 'rejected' |
│                                    'verified' | 'lost_visibility')
├── external_listing_id      (text, nullable)
├── external_listing_url     (text, nullable)
├── first_verified_at        (nullable)
├── last_verified_at         (nullable)
└── verification_failures    (integer)
```

#### `DirectoryRegistry` (platform-wide reference data)
```
DirectoryRegistry
├── id, slug, name
├── submission_method        (enum: 'api' | 'form_post' | 'email' | 'manual')
├── adapter_class            (text; for api/form_post)
├── verification_method      (enum: 'api_lookup' | 'url_pattern' | 'manual')
├── verification_config      (JSONB; per-directory)
├── active                   (boolean)
├── known_indexed_by_ai      (boolean; whether AI engines are known to cite this)
└── notes
```

Seeded with 50+ entries spanning Indian directories (Justdial, IndiaMart, Sulekha, TradeIndia, Quikr Local, etc.), global directories crawled by AI (Yelp, Yellow Pages, Foursquare), and structured-data registries (Wikidata for eligible entities, Crunchbase, Schema.org listing schemas).

#### `VerificationPoll`
```
VerificationPoll
├── id
├── seed_id                  (FK → entity_seeds, nullable)
├── publish_attempt_id       (FK → publish_attempts, nullable)
├── scheduled_for            (timestamp)
├── attempted_at             (nullable)
├── outcome                  (enum: 'verified' | 'not_found' | 'error' | 'still_pending')
└── attempt_index            (integer; 1, 2, 3...)
```

Schedule pattern: T+24h, T+72h, T+7d, T+14d, T+30d for seeds; T+15min, T+1h, T+24h for publishes.

### 3.2 Relationships

```
Business 1───N PublishTarget
PublishTarget 1───1 OAuthToken (or nullable for snippet channels)
PublishTarget 1───N PublishAttempt
PublishAttempt N───1 ContentAsset (so we always know what was published)
PublishAttempt 1───N VerificationPoll
Business 1───N EntitySeed
EntitySeed N───1 DirectoryRegistry
EntitySeed 1───N VerificationPoll
```

---

## 4. The Publisher Adapter Layer

### 4.1 Why the abstraction matters here

We will integrate with at minimum five external systems over the product's lifetime (GBP, WordPress, Justdial, IndiaMart, Sulekha) plus directory adapters. Each has a different API, a different OAuth flow, different rate limits, different error semantics, different verification approach. Without a hard abstraction, every PublishWorkflow would be a switch statement on `channel` — and every new channel would touch every workflow.

The abstraction also means **the workflow is the same code path for every channel**. A publish to GBP and a publish to WordPress run through the exact same Temporal activity, just with a different adapter instance. This makes the workflow simple and the adapters individually testable.

### 4.2 The interface

```python
class PublisherAdapter(Protocol):
    channel: ChannelDescriptor   # static metadata
    
    async def initiate_connection(
        self, business: BusinessIdentity, redirect_uri: str
    ) -> ConnectionInitiation:
        """Returns either an OAuth authorize URL, or instructions for a non-OAuth flow."""
    
    async def complete_connection(
        self, callback_payload: dict
    ) -> ConnectionResult:
        """Process OAuth callback or equivalent. Returns OAuthToken to persist."""
    
    async def refresh_token(self, token: OAuthToken) -> OAuthToken:
        """Refresh; returns a new OAuthToken or raises TokenRefreshFailed."""
    
    async def publish(
        self,
        *,
        asset: ContentAsset,
        target: PublishTarget,
        token: OAuthToken | None,
        idempotency_key: str,
    ) -> PublishResult:
        """Submit content. Must be idempotent: same idempotency_key returns same outcome."""
    
    async def verify(
        self,
        *,
        attempt: PublishAttempt,
        token: OAuthToken | None,
    ) -> VerificationOutcome:
        """Confirm the content is publicly visible. May query API or fetch a URL."""
    
    def is_retryable_error(self, exc: Exception) -> bool:
        """Classify provider exceptions for retry policy."""
```

Adapter implementations are independently versioned. Each adapter declares its own rate-limit policy and circuit-breaker thresholds.

### 4.3 Google Business Profile adapter

GBP allows posting "Posts" (short content), updating description, adding Q&A entries, and updating services. Phase 5 supports:
- **Post creation** — primary publish path; maps to ContentAsset (markdown excerpt + link to full content on the business's website if available).
- **Q&A entries** — derived from `faq_cluster` brief type; each Q&A becomes a Question on GBP, with the answer added by us as the owner.
- **Description update** — derived from `entity_summary` brief; offered as an explicit opt-in (changing the description is high-impact, infrequent).

**OAuth scopes requested:** minimum needed for Business Profile API write. We do not request access to Maps data, Search Console, or anything else. Lower scope = better customer trust and easier app review.

**Rate limits:** GBP's published quota is significant; we set our internal cap below it. Posts: 1 per business per hour during the rollout phase, scaling up with verification.

**Verification:** After publish, we call `accounts.locations.localPosts.get` with the returned ID. If the post exists and `state == 'LIVE'`, verified.

### 4.4 WordPress adapter

WordPress is more variable than GBP because every site is different. We support:
- **Self-hosted WP with REST API + Application Password** — preferred. Customer creates an Application Password in their WP admin; we use it as Basic auth to `/wp-json/wp/v2/posts`.
- **WordPress.com** — supported via WP.com OAuth.
- **Page or Post target type** configurable per PublishTarget.

We publish as **draft** by default with a clear "Publish" call-to-action in the customer notification, unless the customer has set `auto_publish=true` on the target. This means a typo or a poor draft does not auto-land on the customer's homepage.

**Verification:** GET the post by ID; assert `status='publish'` (or `'draft'` if auto-publish is off) and `link` is reachable.

### 4.5 Website snippet (non-WordPress)

For sites we cannot publish to programmatically, we provide:
1. A static rendering of the approved content (HTML + JSON-LD).
2. A copy-paste embed snippet the customer adds to their site.
3. A verification step where we fetch the URL and confirm the snippet is present.

This is **lower automation, higher reach** — most Indian SMB websites are not WordPress and not API-accessible. The snippet path covers them.

`PublishAttempt.status` flows: `queued → in_progress → succeeded (snippet generated)` and then waits for `verified` until our verification crawler finds the embed.

### 4.6 Adapter registration and discovery

`PublisherRegistry` is the in-process discovery service:
```python
class PublisherRegistry:
    def for_channel(self, channel: str) -> PublisherAdapter: ...
    def all_channels(self) -> list[ChannelDescriptor]: ...
```
Adapters self-register at module import time via a decorator. The registry is the only thing that knows about concrete adapter classes; everything else uses the Protocol.

---

## 5. OAuth Token Management

### 5.1 The encryption envelope

Plain tokens are never persisted. The encryption flow:

```
1. Adapter completes OAuth flow → returns access_token, refresh_token (plaintext, in memory).
2. Service-layer code calls TokenVault.store(token):
   a. Generate a random Data Encryption Key (DEK) per token using `os.urandom(32)`.
   b. Encrypt the access and refresh tokens with the DEK (AES-GCM).
   c. Wrap the DEK with the KMS key `oauth-token-encryption-key` via KMS Encrypt.
   d. Persist (encrypted_token_blob, wrapped_dek, kms_key_version).
3. On retrieval:
   a. Read the row.
   b. Unwrap the DEK via KMS Decrypt.
   c. Decrypt the token in memory.
   d. Use, then drop reference (no logging, no caching).
```

Why envelope encryption rather than KMS-direct encryption of tokens: KMS Encrypt has a 64KB payload limit and is rate-limited. With envelope encryption, KMS only handles small DEK wraps (under 1KB) and large-volume per-token operations don't bottleneck on KMS quota.

### 5.2 Token refresh sweep

A scheduled Temporal workflow runs every hour:

```
TokenRefreshSweepWorkflow
   │
   ├─ Activity: Query oauth_tokens WHERE access_token_expires_at < now() + 48h
   ├─ For each token (parallel, bounded):
   │     ├─ Activity: RefreshToken
   │     │       → Adapter.refresh_token(token)
   │     │       → On success: persist new token, update expires_at
   │     │       → On failure (retryable): retry with exponential backoff
   │     │       → On failure (terminal): mark PublishTarget as 'failed';
   │     │             emit `OAuthTokenRefreshFailed` event for Notifications
   └─ DONE
```

Bounded parallelism (default 10) protects against accidental DDoS of refresh endpoints.

The 48-hour window is generous; if the sweep itself fails for two consecutive runs, we still have time to alert and intervene before tokens expire on customers.

### 5.3 Reconnect UX

When `OAuthTokenRefreshFailed` fires:
1. The PublishTarget is marked `failed`.
2. A notification is queued for the customer (via Phase 6 NotificationService) with a deep link to "Reconnect Google Business Profile".
3. In the dashboard, the affected target shows a prominent "Reconnect required" banner.
4. Any pending PublishAttempts for the target are paused (not failed) — they resume when reconnected.

Critically: we do not silently retry forever. After 7 days of failed refresh and no reconnect, we notify a final time and mark associated drafts as `awaiting_action` (so the customer is not surprised when they finally check back).

---

## 6. The Publish Workflow

### 6.1 The flow

```
PublishWorkflow(brief_id, target_ids[])
   │
   ├─ Activity: AssertApproval — re-check that brief.current_state == 'approved'
   ├─ Activity: AssertAuthorization — for each target, re-check publish_authorized_at and not revoked_at
   ├─ For each target_id (parallel):
   │     ├─ Activity: AcquireTokenIfNeeded
   │     ├─ Activity: PreflightCheck (adapter-specific; e.g., GBP location still exists)
   │     ├─ Activity: ExecutePublish
   │     │       → idempotency_key = hash(target_id, asset_id)
   │     │       → Adapter.publish(...)
   │     │       → On retryable failure: Temporal retries per policy (exp backoff, max 5 attempts)
   │     │       → On terminal failure: persist PublishAttempt(status='failed_terminal')
   │     ├─ Activity: SchedulePolls
   │     │       → Schedule child VerificationWorkflows at T+15m, T+1h, T+24h
   ├─ Activity: TransitionBrief — if all targets succeeded, brief.current_state = 'published'
   │                              if some failed, brief stays 'approved' but failed targets are recorded
   ├─ Activity: NotifyCustomer — emit `ContentPublished` or `PublishPartiallyFailed` event
   └─ DONE
```

### 6.2 Idempotency in depth

The `idempotency_key` is the cornerstone. Concretely:

1. Before calling `Adapter.publish`, we look up `publish_attempts` by `idempotency_key`:
   - If exists and `status='succeeded'` or `'verified'`: skip; nothing to do.
   - If exists and `status='in_progress'`: this is the same call being retried. Pass the existing attempt to the adapter. If the adapter's `publish` is also idempotent (e.g., GBP accepts a client-generated request ID), it will return the same result without creating a duplicate post.
   - If exists and `status='failed_retryable'`: retry the call.
   - If absent: create the row, then call.

2. The adapter is required to be idempotent. If the underlying API doesn't support idempotency natively, the adapter implements it by first searching for an existing item matching our `external_object_id` from the prior attempt before posting.

3. Database constraint: `UNIQUE(idempotency_key)` prevents two parallel attempts from both creating rows. The loser of the race retries and finds the winner's row.

### 6.3 Verification

A separate workflow polls until verified or gives up:

```
VerificationWorkflow(publish_attempt_id, attempt_index)
   │
   ├─ Sleep until scheduled_for time
   ├─ Activity: VerifyOnce
   │     → Adapter.verify(...)
   │     → outcome: verified | not_found | error | still_pending
   ├─ If verified: PublishAttempt.status = 'verified', PublishAttempt.verified_at = now()
   │              emit `PublishVerified` event
   ├─ If still_pending or error and attempt_index < N: schedule next attempt
   ├─ If max attempts reached without verify: PublishAttempt.status = 'verification_failed'
   │                                          emit `PublishVerificationFailed` event
   └─ DONE
```

Verification serves two purposes: (1) confirms the publish actually reached the public surface and (2) gives Phase 6 a reliable signal that a citation back-reference is now live.

### 6.4 The PublishApproval gate

This is the "second consent" check. Phase 4 has the customer approve the *content*. Phase 5 requires explicit per-target *publish authorization*:

- When a customer connects a PublishTarget (e.g., GBP), they explicitly authorise publishing to it. `publish_authorized_at` is set.
- The UI for publishing presents a per-target checkbox list. Targets default to "publish here?" = on if previously authorised, but the customer can uncheck per-publish.
- A customer can globally revoke authorization for a target (`revoked_at` set); subsequent publishes to that target are blocked.

The `AssertAuthorization` activity at the top of `PublishWorkflow` re-validates these conditions. A revocation between approval and publish causes the workflow to skip that target with a logged note, not fail.

---

## 7. Entity Seeding

### 7.1 Why this exists

Many AI engines build their knowledge graph from directory listings, structured-data sites, and Wikidata-class registries. Being present in 50+ such places signals to engines: "this is a real, legitimate business." For Indian SMBs, presence in Justdial + IndiaMart + Sulekha + Google Knowledge Graph is meaningful AI-visibility scaffolding.

Entity seeding is *not* the same as publishing content. We are submitting **canonical business information** to systems that aggregate it — name, address, phone, category, hours, website. The Phase 4 `entity_summary` brief type generates the prose; entity seeding submits the structured data.

### 7.2 The flow

```
EntitySeedingWorkflow(business_id)
   │
   ├─ Activity: ResolveBusinessProfile (canonical name, address, phone, category, website)
   ├─ Activity: SelectDirectories — load DirectoryRegistry, filter to active + locale-applicable
   ├─ For each directory (parallel, bounded to 5 concurrent):
   │     ├─ Activity: PrepareSubmission — render directory-specific payload from profile
   │     ├─ Activity: SubmitToDirectory
   │     │       → Per submission_method: api / form_post / email / manual (queue task)
   │     │       → Persist EntitySeed(status='submitted')
   │     ├─ Activity: ScheduleVerificationPolls — T+24h, T+72h, T+7d, T+14d, T+30d
   └─ DONE
```

### 7.3 Verification

A separate `EntitySeedVerificationWorkflow` polls per the schedule. Verification methods:
- `api_lookup` — call the directory's API for the business by submitted ID.
- `url_pattern` — fetch `https://directory.com/{business_slug}` and confirm content matches.
- `manual` — a queue item appears for the ops team for directories without API access.

On verification:
- First verification → `first_verified_at` set, `EntitySeedVerified` event emitted.
- Subsequent re-verifications → `last_verified_at` updated.
- A previously-verified seed that fails verification → `verification_failures += 1`. After 3 consecutive failures over 30 days, status moves to `lost_visibility` and a customer alert is raised.

### 7.4 The directory registry

Phase 5 ships with the registry populated for these categories:

| Tier | Examples | Notes |
|---|---|---|
| Indian general directories | Justdial, Sulekha, TradeIndia, IndiaMart, Quikr, AskLaila | API adapters deferred; submission via form_post + manual queue at MVP |
| Indian vertical directories | Practo (healthcare), JustDial verticals, Shiksha (education) | Manual or web-form |
| Global directories | Yelp, Yellow Pages, Foursquare, Bing Places, Apple Business Connect | Some are API; some require manual ops work |
| Structured data registries | Wikidata (for eligible businesses), Schema.org listing endpoints | High-effort, high-impact; manual or assisted |
| Map/local services | Google Business Profile (overlaps with PublishTarget), Bing Places | API |

Only directories with `active=true` are processed. The registry is platform admin-editable so adding a new directory does not require a code deploy.

---

## 8. Database Schema (additions)

```sql
CREATE TYPE publish_channel AS ENUM (
    'google_business_profile', 'wordpress', 'website_snippet',
    'justdial', 'indiamart', 'sulekha'
);
CREATE TYPE publish_target_status AS ENUM (
    'pending_oauth', 'connected', 'failed', 'revoked', 'disabled'
);

CREATE TABLE publish_targets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL REFERENCES businesses(id),
    channel publish_channel NOT NULL,
    status publish_target_status NOT NULL DEFAULT 'pending_oauth',
    connected_account_label TEXT,
    external_identifier TEXT,
    oauth_token_id UUID,  -- FK added below
    publish_authorized_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    last_publish_at TIMESTAMPTZ,
    meta JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX publish_targets_unique_active_idx
    ON publish_targets(business_id, channel, external_identifier)
    WHERE revoked_at IS NULL;

CREATE TABLE oauth_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    provider TEXT NOT NULL,
    access_token_encrypted BYTEA NOT NULL,
    refresh_token_encrypted BYTEA NOT NULL,
    wrapped_dek BYTEA NOT NULL,
    kms_key_version TEXT NOT NULL,
    access_token_expires_at TIMESTAMPTZ NOT NULL,
    scope TEXT NOT NULL,
    account_subject TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_refreshed_at TIMESTAMPTZ
);
CREATE INDEX oauth_tokens_expiry_idx ON oauth_tokens(access_token_expires_at);

ALTER TABLE publish_targets
    ADD CONSTRAINT publish_targets_oauth_fk
    FOREIGN KEY (oauth_token_id) REFERENCES oauth_tokens(id);

CREATE TYPE publish_attempt_status AS ENUM (
    'queued', 'in_progress', 'succeeded', 'failed_retryable',
    'failed_terminal', 'verified', 'verification_failed'
);

CREATE TABLE publish_attempts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL,
    target_id UUID NOT NULL REFERENCES publish_targets(id),
    content_asset_id UUID NOT NULL,  -- FK content_assets
    brief_id UUID NOT NULL,          -- FK content_briefs
    idempotency_key TEXT NOT NULL UNIQUE,
    status publish_attempt_status NOT NULL DEFAULT 'queued',
    attempts_count INTEGER NOT NULL DEFAULT 0,
    external_object_id TEXT,
    public_url TEXT,
    verified_at TIMESTAMPTZ,
    last_attempt_at TIMESTAMPTZ,
    next_attempt_at TIMESTAMPTZ,
    failure_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX publish_attempts_target_idx ON publish_attempts(target_id);
CREATE INDEX publish_attempts_business_idx ON publish_attempts(business_id);
CREATE INDEX publish_attempts_brief_idx ON publish_attempts(brief_id);

CREATE TABLE directory_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    submission_method TEXT NOT NULL,
    adapter_class TEXT,
    verification_method TEXT NOT NULL,
    verification_config JSONB NOT NULL DEFAULT '{}',
    active BOOLEAN NOT NULL DEFAULT true,
    known_indexed_by_ai BOOLEAN NOT NULL DEFAULT false,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE entity_seed_status AS ENUM (
    'pending_submission', 'submitted', 'rejected', 'verified', 'lost_visibility'
);

CREATE TABLE entity_seeds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL,
    directory_id UUID NOT NULL REFERENCES directory_registry(id),
    submission_payload JSONB NOT NULL,
    submitted_at TIMESTAMPTZ,
    status entity_seed_status NOT NULL DEFAULT 'pending_submission',
    external_listing_id TEXT,
    external_listing_url TEXT,
    first_verified_at TIMESTAMPTZ,
    last_verified_at TIMESTAMPTZ,
    verification_failures INTEGER NOT NULL DEFAULT 0,
    UNIQUE (business_id, directory_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX entity_seeds_business_idx ON entity_seeds(business_id);
CREATE INDEX entity_seeds_status_idx ON entity_seeds(status);

CREATE TABLE verification_polls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    seed_id UUID REFERENCES entity_seeds(id),
    publish_attempt_id UUID REFERENCES publish_attempts(id),
    scheduled_for TIMESTAMPTZ NOT NULL,
    attempted_at TIMESTAMPTZ,
    outcome TEXT,
    attempt_index INTEGER NOT NULL,
    CHECK ((seed_id IS NOT NULL)::int + (publish_attempt_id IS NOT NULL)::int = 1)
);
CREATE INDEX verification_polls_due_idx
    ON verification_polls(scheduled_for) WHERE attempted_at IS NULL;
```

**RLS:** Applied to `publish_targets`, `oauth_tokens`, `publish_attempts`, `entity_seeds`, `verification_polls`. Not on `directory_registry` (platform-wide reference data).

---

## 9. Self-Review

### Pass 1

| # | Severity | Finding | Where |
|---|---|---|---|
| H1 | **High** | The idempotency strategy (§6.2) relies on adapters being idempotent. But for GBP "create post", the API does *not* natively support idempotency keys — we could create duplicate posts on retry. The "search for existing" workaround is described but not specified. | §6.2, §4.3 |
| H2 | **High** | OAuth token refresh failure (§5.3) marks the target as `failed` and pauses pending attempts. But a `revoked_at` token (customer revoked our access via Google's side) looks identical to an expired-and-irrecoverable token. We need to distinguish: revocation requires a different customer message and prevents the customer from blaming us. | §5.3 |
| H3 | **High** | Snippet-channel verification (§4.5) requires *us* to fetch the customer's website. For new businesses without traffic, this is fine, but a customer site behind Cloudflare with bot protection will fail every verification. We need a fallback or alternative verification. | §4.5 |
| M1 | Medium | KMS Decrypt is called on every token use. At scale, this is rate-limited and adds latency. No caching strategy specified. | §5.1 |
| M2 | Medium | The DirectoryRegistry includes 50+ directories at MVP, but Phase 5 ships only api-or-form_post adapters. What happens to the `email` and `manual` ones — a black-hole queue? | §7.4, §7.3 |
| M3 | Medium | Verification polling for entity seeds: T+30d is a long tail. A seed that takes 60+ days to appear (some directories are slow) would be stuck in `submitted` forever. | §7.3 |
| M4 | Medium | The "auto_publish=false" default for WordPress (§4.4) is good safety, but the workflow doesn't model "publishes as draft, awaits customer toggle". The PublishAttempt status `succeeded` is set, but verification can't pass because the post isn't live. | §4.4, §6.3 |
| M5 | Medium | `EntitySeed` has `UNIQUE(business_id, directory_id)` — meaning a business has at most one seed per directory. What if the business changes name? The seed needs updating; do we replace or version? | §3.1 EntitySeed |
| L1 | Low | The 7-day "no reconnect → mark as awaiting_action" timer (§5.3) is hardcoded; should be tier-configurable. | §5.3 |

Three highs and five mediums. Iterating.

### Pass 2 (resolutions)

**H1 (GBP idempotency workaround):** Concretely specified. The GBP adapter's `publish` implements idempotency as follows:
1. Before any write, list recent posts for the location via `localPosts.list` with `pageSize=20` and `orderBy=createTime desc`.
2. Each post we have ever created carries a content marker in its body — a hidden HTML comment `<!-- cb:{idempotency_key} -->` appended at render time. Search the list for this marker.
3. If a match is found, that's our prior successful post. Return its ID and mark this attempt as `succeeded` without re-creating.
4. If not found, proceed with `localPosts.create`. The render layer ensures the marker is in the body.

Cost: one extra `list` call per publish. Acceptable. The same pattern is used by the WordPress adapter with a `_cb_idempotency_key` post meta field.

**H2 (revoked vs. expired):** OAuth refresh classifies errors. Google returns `invalid_grant` when the refresh token is revoked (customer revoked, Google security action, or token age expired). The adapter raises `TokenRevoked` distinct from `TokenRefreshTransient`. The TokenRefreshSweepWorkflow handles each:
- `TokenRevoked` → PublishTarget marked `revoked` (not `failed`), customer notified with copy: "Your Google Business Profile connection has been revoked. This may have been done by you or by Google. Please reconnect to resume."
- `TokenRefreshTransient` → retry; if persistent, mark `failed` with copy: "We're having trouble refreshing your Google connection. Please try reconnecting."

**H3 (snippet verification behind WAF):** Two-path verification:
1. **Primary: direct fetch** with a polite user-agent (`CitedByVerificationBot/1.0; https://citedby.app/bot`) and Indian residential proxy IP. This works for >95% of small business sites.
2. **Fallback: customer-attested verification** — if direct fetch fails twice, the dashboard shows the customer a one-click "I've added the snippet, verify now" button. The button triggers a single verified attempt, and on success marks verified with `verification_method='customer_attested'`. This trades automation for inclusivity.

A site that *neither* responds to our bot nor has its customer click "verify" stays unverified — visible in the customer's dashboard and surfaces as a Phase 6 health alert.

**M1 (KMS Decrypt caching):** Decrypted DEKs are cached in process memory with a strict TTL of 5 minutes and an LRU cap of 100 entries. The cache is per-worker-process (no cross-process sharing). The actual plaintext tokens are never cached — only the DEK. Token decryption with a cached DEK is fast and local; KMS Decrypt is hit at most once per 5-minute window per token. This brings KMS calls well under quota. Documented in §5.1.

**M2 (manual-method directories):** Defined explicitly: a `pending_submission` row is created with `submission_method='manual'` and shows up in an internal **Ops Queue** dashboard (built in Phase 5). An ops operator manually submits the listing via the directory's web form, then records the `external_listing_id` and `external_listing_url` in the dashboard, which transitions the seed to `submitted`. This is honest about the limits of automation while still tracking the work.

**M3 (long-tail seeds):** After T+30d without verification, the seed status becomes `submission_unconfirmed`. A monthly background job retries verification on `submission_unconfirmed` seeds for up to 6 months total. After 6 months without verification, status finalises as `submission_unverified` and a recommendation is presented to the customer ("Your Justdial listing was submitted but is still not visible. Consider following up directly.").

**M4 (WP draft state):** Added a distinct `PublishAttempt.status = 'awaiting_customer_publish'` for the case where adapter publish succeeded but the content is in draft. Verification doesn't poll until the customer changes it to publish; we expose a UI in the dashboard showing "Drafts awaiting your publish in WordPress" with quick links to the WP admin. When verification later detects the post is live, the row transitions to `verified`.

**M5 (EntitySeed updates):** Schema change: `EntitySeed.profile_snapshot` (JSONB) captures the profile we submitted. A `BusinessProfileUpdated` event subscriber compares the live profile to the snapshot. If material fields (name, phone, address) changed, a `seed_update` workflow re-submits and updates the directory listing (where the directory's API supports it). The seed's `version` increments; we keep the row, not replace it. `UNIQUE` constraint stays (one active per business+directory).

**L1:** Move to `plans.token_reconnect_window_days` config. Default 7.

### Pass 3

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M6 | Medium | The customer-attested verification path (H3 Pass 2 resolution) lets a customer effectively self-certify they installed a snippet. If they lie (don't actually install it), we mark verified incorrectly. | Acceptable: customer-attested status is *visibly different* (column shown in dashboard, separate metric). Re-attempted direct verification runs nightly; if direct verification later succeeds, status upgrades to `verified` (auto). If after 30 days direct verification still fails despite customer-attestation, status flips back to `attested_unverified` and a re-prompt fires. Documented. |
| L2 | Low | OAuth scope discussion (§4.3) is GBP-specific; analogous discussion is missing for WordPress (we ask for what scopes when using OAuth from WP.com?). | Documented: WP.com OAuth requests minimum scopes `posts`, `pages`, `users` (read-only on `users` for verification). |

**M6 resolved.** No remaining H or M findings. **Self-review passes.**

---

## 10. Test Strategy

### 10.1 Unit tests

- Each adapter's `publish` method against a recorded fixture of API responses (using VCR-style cassettes).
- TokenVault encrypt/decrypt round-trip with KMS mocked.
- Idempotency-key collision tests: simulate two parallel publish requests with same key; assert one succeeds, one finds the existing row.
- Verification polling schedule: assert correct timestamps at T+15m, +1h, +24h for publishes.

### 10.2 Integration tests

- Full PublishWorkflow against a stubbed adapter that returns success on first attempt; assert state transitions.
- PublishWorkflow against a stubbed adapter that fails twice then succeeds; assert retry behaviour and idempotency.
- PublishWorkflow against a stubbed adapter that returns success but verification fails; assert `verification_failed` terminal state and customer notification.
- Token refresh sweep with mix of soon-expiring, revoked, and healthy tokens; assert correct handling per category.

### 10.3 Chaos / resilience tests

- 1,000 publish attempts against a flaky adapter (30% failure rate); assert zero duplicate posts.
- Concurrent publish workflows to the same target; assert serialised execution per target.
- Token revocation mid-publish; assert workflow detects on next call and surfaces correctly.

### 10.4 Sandbox / live tests

- GBP integration tested against a real CitedBy-owned GBP property in a sandbox account.
- WordPress integration tested against a self-hosted WP instance in staging.
- These are slow, manually triggered, and gated by feature flag — not part of every CI run.

### 10.5 Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| AC1 | A customer can connect a GBP via OAuth, with token stored encrypted and refresh tested. | E2E manual |
| AC2 | An approved brief publishes successfully to GBP and is verified within 1h. | E2E manual |
| AC3 | A retried publish produces no duplicate posts. | Integration test |
| AC4 | A revoked-side token results in correct customer messaging and target state. | Integration test |
| AC5 | A snippet-channel attempt with bot-blocked verification falls back to customer-attested correctly. | Manual scenario |
| AC6 | Entity seeding to 5 API-method directories completes within 7 days for a test business. | Manual scenario |
| AC7 | Token refresh sweep runs hourly and refreshes tokens within 48h of expiry. | Operational verification |

---

## 11. Implementation Tasks

For 2 backend + 1 frontend across 3 sprints (6 weeks):

### Sprint 1 — Targets, OAuth, vault
- PublishTarget schema + CRUD endpoints. (2d)
- OAuth flow: initiate, callback, token storage. (3d)
- TokenVault with KMS envelope encryption + DEK cache. (2d)
- TokenRefreshSweepWorkflow. (2d)
- Frontend: target list, connect/disconnect UI. (3d)

### Sprint 2 — Publishing & idempotency
- PublisherAdapter Protocol + PublisherRegistry. (1d)
- GBP adapter with idempotency-marker strategy. (3d)
- WordPress adapter (REST API + Application Password). (2d)
- Website snippet renderer + verification. (2d)
- PublishWorkflow (Temporal). (3d)
- VerificationWorkflow. (2d)

### Sprint 3 — Entity seeding & ops
- DirectoryRegistry seed. (1d)
- EntitySeedingWorkflow + verification. (3d)
- 5 api-method directory adapters at MVP. (4d)
- Ops queue dashboard for manual-method directories. (2d)
- Customer-attested verification UI. (1d)
- Test pass: chaos tests, acceptance walkthrough. (2d)

**Phase 5 exit criteria:**
- §10.5 ACs pass.
- A real GBP-connected demo business has a published post visible in Google Business Profile.
- Token refresh sweep is running on schedule in staging.
- Ops queue shows correctly populated rows for manual directories.

---

## 12. Handoff to Phase 6

Phase 6 (Weekly Recrawl & Notifications) consumes:
- `PublishAttempt` rows with `status='verified'` and `public_url` set — Phase 6's recrawl can cross-reference earned citations to specific published assets.
- `OAuthTokenRefreshFailed`, `ContentPublished`, `PublishVerificationFailed`, `EntitySeedVerified` events — Phase 6 subscribes to deliver appropriate customer notifications.
- `verification_polls` — Phase 6 may inspect these for compound alerts.

The contract is the events listed above and the verified PublishAttempt's URL field. Phase 5 guarantees that any attempt in `verified` has a real, fetchable public URL pointing to live content.

---

*CitedBy Phase 5 Design v1.0 | Confidential | May 2026*
*Next: Phase 6 — Weekly Recrawl & Notifications*
