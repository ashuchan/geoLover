# CitedBy — Phase 2 Design
## Audit & Citation Detection
**Version:** 1.0
**Status:** Approved for implementation
**Date:** May 2026
**Author:** CTO, CitedBy
**Parent document:** `CitedBy_HLD_v1.md`
**Modules covered:** Audit & Crawl (#3)

---

## 1. Phase Overview

### 1.1 Why this matters more than anything else

Phase 2 is the technical heart of CitedBy. Three things are decided here:

1. **Whether customers trust us.** If our citation detection has false positives, we tell customers they're already winning when they're not. If we have false negatives, we tell them they're losing when they're already cited. Either is fatal for the brand.
2. **Whether we are operationally viable.** Engine probing is our largest infrastructure variable cost and our largest source of operational fragility. Wrong design here means we either go broke on proxy/LLM fees or our audits silently fail.
3. **Whether the product can grow.** New engines (Sarvam, Krutrim) are Phase 2; new query categories, new locales — all of these depend on Phase 2's adapter and template design being extensible.

This phase is also where the rubber meets the road on the architectural principle that "external systems are adapters." Five engines, five access patterns, five failure modes. If we don't isolate them rigorously, every new engine destabilises every customer.

### 1.2 What this phase delivers

By the end of Phase 2:

- A `BusinessIdentity` resolution service builds a complete identity object (canonical name, normalized aliases, transliteration candidates, phone, website, location signals) for any business.
- An `EngineRegistry` holds descriptors for all supported AI engines, with health, cost, rate limit, and capability metadata.
- Three production engine adapters: `OpenAIChatAdapter`, `PerplexityAdapter`, `GoogleAIOverviewsScrapeAdapter`. Each implements the `AIEngineAdapter` protocol.
- A `QueryTemplate` system: templates live in the database, are parameterised, and are versioned. A category-aware query-generation algorithm produces ~50 queries per audit.
- The `CitationDetector`: a multi-stage, deterministic algorithm that decides whether a free-text response cites a given business, returning confidence + match type + snippet + polarity.
- An `AuditWorkflow` (Temporal) that orchestrates query generation → engine fan-out → citation detection → score computation → competitor extraction → audit-run persistence.
- An `AIVisibilityScore` calculator with explicit math, transparent inputs, and stable behaviour across versions.
- Raw engine response archival to GCS for re-running detection without re-crawling.
- A `ProxyGateway` and `LLMGateway` that meter cost per business and enforce budgets.
- Engine health monitoring with automatic unhealthy-marking and degradation.
- Citation polarity detection (basic Phase-2 sentiment around the citation snippet).

### 1.3 What this phase does NOT deliver

- No automatic content generation in response to audit findings (Phase 4).
- No "Top 3 Quick Wins" generation via LLM (deferred to Phase 3 where the report and the prompts naturally live together).
- No vernacular (Hindi, Kannada, Tamil) query templates or detection (post-MVP; the adapter interface accepts `locale` so it slots in).
- No Sarvam or Krutrim engine adapters (post-MVP; the interface is ready).
- No real-time citation alerting (Phase 6 weekly recrawl serves the alerting role at MVP).
- No PDF report generation (Phase 3).
- No public free-audit UI (Phase 3).

---

## 2. Requirements

### 2.1 Functional requirements (traced from PRD §3.1 Module 1)

| # | Requirement | Source |
|---|---|---|
| F1 | Given a Business, the system produces ~50 category-and-location-shaped queries. | PRD §3.1 1.2 |
| F2 | Queries are dispatched to all healthy engines in the registry. | PRD §3.1 1.2 |
| F3 | Each engine returns a natural-language response that is archived raw to GCS. | Architectural requirement |
| F4 | Citation detection runs on each response, producing a `CitationResult` per (engine, query). | PRD §3.1 1.3 |
| F5 | An audit completes in <5 minutes p95. | PRD acceptance criteria |
| F6 | Competitors are auto-discovered from lost queries (businesses that were cited where ours was not). | PRD §3.1 1.3 |
| F7 | A composite `AIVisibilityScore` (0–100) is computed deterministically from citation counts and weights. | PRD §3.1 1.3 |
| F8 | The complete audit is persisted as an immutable `AuditRun`. | Reproducibility requirement |
| F9 | Engine adapter failures do not block the audit; partial completion is reported. | Resilience requirement |
| F10 | Every audit records `algorithm_version` and `query_template_set_version` to support reproducibility. | HLD risk register |

### 2.2 Non-functional requirements

| # | Requirement | Target |
|---|---|---|
| NF1 | Audit p95 end-to-end latency | <5 minutes |
| NF2 | Audit p99 latency | <8 minutes |
| NF3 | Citation detection precision on labelled benchmark | ≥0.90 |
| NF4 | Citation detection recall on labelled benchmark | ≥0.85 |
| NF5 | Cost per audit (3 engines, 50 queries, MVP) | ≤₹40 |
| NF6 | Audits can be re-detected (detection re-run on archived responses) without re-crawl | Yes |
| NF7 | Adding a new engine adapter requires zero changes to AuditWorkflow code | Adapter interface alone |
| NF8 | Engine unhealthy state surfaces in dashboard | <60s from detection |

---

## 3. Domain Model — Detailed

### 3.1 Aggregates

#### `BusinessIdentity` (value object, not persisted as separate aggregate)
Composed from the Phase 1 Business + its locations + aliases. The Audit module reads this via `BusinessProfileService.getIdentity(business_id)`.

```
BusinessIdentity
├── business_id            (UUID, scoping)
├── canonical_name         (string)
├── name_normalized        (lower-case, whitespace-collapsed, diacritic-stripped)
├── aliases                (list of NormalisedAlias)
├── phone_e164             (optional, normalised)
├── website_etld_plus_one  (optional, e.g. "sharmadental.in")
├── primary_locality       (e.g. "Koramangala")
├── primary_city           (e.g. "Bengaluru")
├── name_uniqueness_score  (float, 0-1; computed)
└── identity_signal_set    (multiset for matching)
```

The `identity_signal_set` is the precomputed set of tokens, phrases, and patterns the CitationDetector uses. Construction is deterministic and cached.

#### `QueryTemplate`
```
QueryTemplate
├── id                    (UUID)
├── category_id           (FK → Category)
├── subcategory_id        (FK → Category, nullable)
├── locale                (default 'en-IN')
├── template_text         (e.g., "Best {subcategory} in {locality} {city}")
├── variables_required    (string[]; e.g., ['subcategory','locality','city'])
├── intent_type           (enum: 'informational' | 'comparative' | 'transactional' | 'navigational')
├── priority              (integer; for selection ordering)
├── active                (boolean)
├── version               (integer; bumped on each material change)
├── template_set_id       (FK; groups templates that ship together)
└── created_at, updated_at
```

**Invariants:**
- `template_text` must reference only `variables_required`.
- Templates within a `template_set_id` are deployed atomically; an AuditRun references a single template_set_id.

#### `EngineDescriptor`
```
EngineDescriptor
├── id                    (UUID)
├── engine_key            (string, unique; e.g., 'openai-chat-v1', 'perplexity-online-v1')
├── display_name          (e.g., 'ChatGPT')
├── adapter_class         (FQN of Python class; resolved at runtime)
├── access_method         (enum: 'api' | 'scrape' | 'partnership_api')
├── supported_locales     (string[])
├── cost_per_call_inr     (decimal; current expected cost)
├── rate_limit_per_minute (integer)
├── concurrency_limit     (integer)
├── timeout_seconds       (integer)
├── health_status         (enum: 'healthy' | 'degraded' | 'unhealthy' | 'paused')
├── health_last_checked_at
├── active                (boolean; manual on/off)
└── config_json           (jsonb; adapter-specific config)
```

**Invariants:**
- `engine_key` is the registry primary key used across the system.
- `health_status` is updated by the monitor, not directly by the application.
- `cost_per_call_inr` is the *budgeted* cost; actual cost recorded per call.

#### `AuditRun`
```
AuditRun
├── id                          (UUID)
├── tenant_id                   (UUID, RLS)
├── business_id                 (UUID, FK)
├── trigger                     (enum: 'free_audit' | 'initial' | 'weekly' | 'manual' | 'api')
├── status                      (enum: 'pending' | 'running' | 'partial' | 'completed' | 'failed')
├── algorithm_version           (string; CitationDetector version at time of run)
├── template_set_id             (FK)
├── started_at, completed_at
├── total_queries               (int)
├── total_engines               (int)
├── successful_engines          (int)
├── failed_engines              (int)
├── completeness_pct            (float; successful / total)
├── total_cost_inr              (decimal)
├── ai_visibility_score         (float, 0-100)
├── workflow_id                 (Temporal workflow ID; nullable in case of legacy runs)
├── error_summary               (jsonb; nullable)
└── created_at
```

**Invariants:**
- An AuditRun is **immutable** once `status` reaches `completed`, `partial`, or `failed`.
- `algorithm_version` and `template_set_id` are pinned at creation; later algorithm changes do not affect this run.
- A `partial` audit has `completeness_pct >= 60%`; below that it's `failed`.

#### `QueryExecution` (a row per (audit_run, query, engine))
```
QueryExecution
├── id                          (UUID)
├── tenant_id, business_id      (denorm for RLS and queries)
├── audit_run_id                (FK)
├── query_template_id           (FK)
├── filled_query_text           (string; the actual query sent)
├── engine_key                  (string)
├── status                      (enum: 'pending' | 'in_flight' | 'succeeded' | 'failed' | 'skipped')
├── attempt_count               (int)
├── raw_response_gcs_uri        (string; nullable; populated on success)
├── raw_response_truncated      (text; first 4KB for fast access)
├── response_latency_ms         (int)
├── cost_inr                    (decimal)
├── error_code                  (string, nullable)
├── error_detail                (text, nullable)
├── executed_at                 (timestamptz)
└── created_at
```

**Invariants:**
- One QueryExecution per (audit_run, query_template, engine_key) — uniqueness enforced.
- Successful executions always have `raw_response_gcs_uri` populated.

#### `Citation` (a row when detection finds a match)
```
Citation
├── id                          (UUID)
├── tenant_id, business_id      (denorm)
├── query_execution_id          (FK)
├── audit_run_id                (denorm, indexed)
├── match_type                  (enum: 'exact_name' | 'alias' | 'phone' | 'website' | 
│                                       'address' | 'fuzzy_name' | 'composite')
├── confidence                  (float, 0-1)
├── snippet                     (text; the cited text excerpt, ~280 chars)
├── snippet_start_pos           (int; offset in response)
├── polarity                    (enum: 'positive' | 'neutral' | 'negative')
├── corroborating_signals       (text[]; signals beyond the primary match)
├── algorithm_version           (string)
└── created_at
```

**Invariants:**
- A Citation always has at least one `match_type` and `confidence >= 0.5`.
- A citation with `confidence < 0.8` requires at least one corroborating signal to be persisted.

#### `CompetitorObservation` (transient discovery; rolled up into business_competitors)
```
CompetitorObservation
├── id, tenant_id, business_id, audit_run_id
├── query_execution_id          (FK)
├── competitor_name             (text; raw)
├── competitor_name_normalized
├── competitor_signals          (jsonb; what we matched on)
├── confidence                  (float)
└── observed_at
```

After each AuditRun completes, an aggregation pass clusters observations by `competitor_name_normalized`, upserts into `business_competitors` (Phase 1 table), and links the discovery audit.

### 3.2 Relationship overview

```
Business 1───N AuditRun 1───N QueryExecution 1───{0..N} Citation
                                          │
                                          1───N CompetitorObservation
                                                  │
                                                  └ aggregated into business_competitors
```

---

## 4. The Engine Adapter Layer

### 4.1 The protocol

```python
class AIEngineAdapter(Protocol):
    """The contract every engine implementation must satisfy.
    Implementations live in audit/adapters/ and register themselves with the EngineRegistry.
    """
    
    descriptor: EngineDescriptor
    
    async def probe(
        self,
        query: QueryIntent,
        *,
        budget: ProbeBudget,
        timeout_override_s: float | None = None,
    ) -> EngineResponse:
        """Submit the query, return the raw natural-language response.
        Must respect rate limit, timeout, and cost budget.
        Must surface errors via well-typed exceptions, never return partial-success silently.
        """
    
    async def health_check(self) -> HealthStatus:
        """Synthetic probe used by the monitor. Lightweight; cheap."""
    
    def supports_locale(self, locale: Locale) -> bool: ...
    
    def estimated_cost(self, query: QueryIntent) -> Money: ...
```

`EngineResponse` is a value object containing: raw response text, headers/metadata returned (if any), exact tokens-used or page-bytes-fetched, latency, and a fingerprint (hash of input + engine version) used for caching.

`ProbeBudget` encapsulates: remaining budget for the parent operation (audit), per-engine rate limit token, deadline.

### 4.2 Concrete adapters for MVP

#### `OpenAIChatAdapter`

- Uses OpenAI Chat Completions API (model: `gpt-4o-mini` for cost, escalating to `gpt-4o` if a query needs it).
- Submits the query as a user message with a wrapping system prompt: *"You are a helpful local search assistant. Answer naturally."* The system prompt is **fixed** and versioned — it must remain stable so we measure the engine, not our prompting.
- Returns the raw assistant message text as the response.
- Rate limit: per OpenAI org limits; soft-capped to 60 RPM in our adapter.
- Estimated cost: ~₹0.15 per query at `gpt-4o-mini`.

#### `PerplexityAdapter`

- Uses Perplexity API (model: `pplx-online`).
- Perplexity's online model returns answers with embedded citations. We capture both the answer text and the citation URLs returned in the response metadata.
- Citation URLs are passed to the CitationDetector as additional signals (website match becomes very strong).
- Rate limit: per Perplexity API limits.
- Estimated cost: ~₹0.30 per query.

#### `GoogleAIOverviewsScrapeAdapter`

- **The risky one.** No API; we scrape.
- Uses Playwright in headed-emulation mode through a residential proxy pool (Bright Data/Smartproxy, India-resident IPs).
- For each query: navigate to `https://www.google.com/search?q={query}&hl=en-IN&gl=IN`, wait for AI Overview module to render or for a "no overview" signal, extract the overview text via DOM selector.
- Robust against minor selector changes via a multi-selector strategy (primary + fallback selectors maintained in config).
- Rate limit: aggressive throttling, ~12 RPM per proxy IP, with randomised delay and request fingerprint variation.
- Estimated cost: ~₹0.80 per query (proxy bandwidth + compute).
- **Degradation mode (HLD Risk R1):** if failure rate >30% over a 10-minute rolling window, the engine is marked `unhealthy` and excluded from new audits automatically.

### 4.3 The EngineRegistry

`EngineRegistry` is a runtime singleton populated from the `engine_descriptors` table at app start (and on config-update events). It exposes:

```python
class EngineRegistry:
    def get(self, engine_key: str) -> AIEngineAdapter: ...
    def list_healthy(self, locale: Locale) -> list[AIEngineAdapter]: ...
    def list_for_audit(self, audit_spec: AuditSpec) -> list[AIEngineAdapter]: ...
    def mark_unhealthy(self, engine_key: str, reason: str) -> None: ...
    def mark_healthy(self, engine_key: str) -> None: ...
```

A background `EngineHealthMonitor` runs in each worker pool, periodically calling `health_check()` on every active engine. Result is written to `engine_descriptors.health_status` with a timestamp. Cloud Monitoring dashboards read from this table.

### 4.4 Cost and rate limiting — the gateways

Every engine call goes through one of two gateways:

- **`LLMGateway.complete(...)`** for API-based engines (OpenAI, Perplexity, Anthropic). Pre-checks per-business + per-platform budget, then dispatches. Records cost post-call.
- **`ProxyGateway.fetch(...)`** for scraping engines. Same pattern with proxy bandwidth costs.

Both gateways are the **only** way the system contacts external AI services. Adapters cannot import `openai` or `playwright` directly; they go through the gateway. This is enforced by a CI check.

This gives us:
- One place to add a new provider's billing.
- One place to add caching of identical deterministic prompts.
- One place to flip the platform kill switch.

---

## 5. Query Generation

### 5.1 The QueryGenerator

```python
class QueryGenerator:
    def generate(
        self,
        business: BusinessIdentity,
        *,
        template_set_id: UUID,
        max_queries: int = 50,
    ) -> list[QueryIntent]:
        """Select templates appropriate for the business's category and subcategories.
        Fill variables from business identity.
        Deduplicate. Order by priority. Trim to max_queries."""
```

Variable filling logic:
- `{category}` → human-readable category name (e.g., "CA firm", "dental clinic")
- `{subcategory}` → first subcategory's name
- `{locality}` → primary location locality
- `{city}` → primary location city
- `{service_type}` → drawn from business keywords (multiple values → multiple queries)
- `{state}` → primary location state

A template `"Best {subcategory} in {locality} {city}"` with a CA firm in Koramangala produces: `"Best CA firm in Koramangala Bengaluru"`.

If a template requires a variable the business doesn't have, the template is skipped (logged for diagnostics).

### 5.2 Template set selection

When an AuditRun starts:
- If `business.category` has a `default_query_template_set_id`, use it.
- Otherwise use the global default set.
- Template set is pinned to the AuditRun for reproducibility.

Operators can create experimental template sets and assign them to specific tenants for A/B testing (Phase 4-onwards capability; the data model supports it from Phase 2).

### 5.3 Phase-2 default template set (seed)

For each subcategory, 8–12 templates spanning informational, comparative, transactional intents. Examples for CA Firm:

- *Informational:* "What does a CA firm in {locality} do?"
- *Comparative:* "Best CA firm in {locality} for GST filing"
- *Transactional:* "CA firm near {locality} accepting new clients"
- *Comparative+geo:* "Top CA firms in {city} for startups"

Multiplied across 5 subcategory entries per category and ~5 active categories, the seed produces ~250 templates. Each business uses ~50 selected for its profile.

---

## 6. The Citation Detection Algorithm

This is the single most consequential algorithm in the product. The design must be:
- **Deterministic** (same input → same output).
- **Explainable** (we can say *why* a match was declared).
- **Versioned** (we know which algorithm version produced a result).
- **Re-runnable** (we can run a new version on old raw responses).

### 6.1 Stages (executed in order; first sufficient match wins, but all matches recorded)

| Stage | Method | Confidence base | Notes |
|---|---|---|---|
| 1 | Exact canonical name match (case-insensitive, whitespace-normalised) | 0.99 | Must be word-boundary; substring matches rejected |
| 2 | Alias match (any user-entered alias, normalised) | 0.95 | Same word-boundary requirement |
| 3 | Phone number match (E.164 normalised, both in response and identity) | 0.99 | Phone is high-specificity; numbers rarely shared |
| 4 | Website domain match (eTLD+1) | 0.95 | Subdomain variations covered |
| 5 | Address fingerprint match (locality + street tokens, fuzzy) | 0.80 | Requires ≥2 locality/street tokens |
| 6 | Fuzzy name match (Jaro-Winkler ≥ 0.92 + locality corroboration) | 0.75 | Only triggers if stages 1-5 negative |
| 7 | Composite (low-uniqueness name + 2+ corroborating signals) | 0.85 | For generic names like "Sharma Dental" |

### 6.2 Corroborating signals and confidence boosting

When a primary match is found, the detector also scans for corroborating signals:
- Locality name appears near the citation (within ±200 chars)
- City name appears near the citation
- Phone appears anywhere in the response
- Website appears anywhere
- Service keyword appears near the citation

Each corroborating signal adds +0.05 to confidence, capped at 0.99.

### 6.3 The `name_uniqueness_score`

For each business, a precomputed `name_uniqueness_score` (range 0-1) gates which stages are sufficient on their own:

- score ≥ 0.7 (high entropy, e.g. "Bhargav Krishnamurthy CA Firm"): stages 1-2 are sufficient alone
- score < 0.7 (low entropy, e.g. "Sharma Dental"): require at least one corroborating signal even for stage 1-2 matches
- score < 0.4 (extremely generic, e.g. "City Clinic"): require ≥2 corroborating signals

The uniqueness score is computed by a separate process (Phase 2 includes a simple version: token-rarity over a corpus; later improvements possible).

### 6.4 Polarity (sentiment around the citation)

Within ±200 chars of the citation snippet, run a lightweight sentiment classification (rule-based at MVP — looking for negative cue words like "avoid", "scam", "complaints", "poor", "bad reviews" within proximity, plus a basic lexicon).

Polarity classification:
- `negative`: any negative cue near the citation
- `neutral`: no clear sentiment
- `positive`: positive cue words ("recommended", "top-rated", "trusted")

A negative-polarity citation is still a citation (the business is mentioned), but is flagged distinctively in reports. This avoids the embarrassing failure mode of celebrating "you appeared in 3 answers!" when one of those was "avoid Sharma Dental, they overcharge."

### 6.5 Output contract

```python
@dataclass(frozen=True)
class CitationResult:
    cited: bool
    confidence: float  # 0-1
    match_type: MatchType
    snippet: str
    snippet_start_pos: int
    polarity: Polarity
    corroborating_signals: list[str]
    competitors_mentioned: list[CompetitorObservation]  # other businesses cited in same response
    algorithm_version: str
```

### 6.6 Algorithm versioning

The detector itself has a semantic version string (e.g., `cd-1.0.0`). Every citation row records this. When the algorithm changes in a way that affects results, the version bumps.

A `RedetectAuditWorkflow` can run against an AuditRun's raw responses (stored in GCS) under a new algorithm version, producing a **new** AuditRun with `trigger='redetection'`. This means:
- Customers' historical reports remain reproducible (old version, old result).
- We can A/B compare detector versions on real production traffic without re-crawling.
- Crucially, this means re-crawling is rarely needed for algorithm work — only when engine outputs change.

---

## 7. The Audit Workflow

### 7.1 Workflow signature

```python
@workflow.defn
class AuditWorkflow:
    @workflow.run
    async def run(
        self,
        input: AuditWorkflowInput,  # business_id, tenant_id, trigger, template_set_id?
    ) -> AuditWorkflowResult:
        ...
```

### 7.2 Execution model

```
1.  Load BusinessIdentity                                     [activity: load_identity]
2.  Resolve template_set + generate queries                   [activity: generate_queries]
3.  Resolve healthy engines from registry (filter by locale)  [activity: resolve_engines]
4.  Create AuditRun record (status='running')                 [activity: create_audit_run]
5.  Fan-out: for each (query, engine), execute probe          [parallel activities]
    └── Each probe activity:
         a. Check budget; if exceeded, abort with error code
         b. Acquire engine rate-limit token
         c. Call adapter.probe()
         d. Archive raw response to GCS
         e. Run citation detection
         f. Persist QueryExecution + Citation(s) + CompetitorObservations
         g. Return summary
6.  Aggregate results                                         [activity: aggregate]
7.  Compute AIVisibilityScore                                 [activity: compute_score]
8.  Roll up CompetitorObservations into business_competitors  [activity: update_competitors]
9.  Finalise AuditRun (status='completed' or 'partial')       [activity: finalise]
10. Emit domain event AuditRunCompleted                       [activity: emit_event]
```

### 7.3 Fan-out concurrency control

Each (query × engine) is one Temporal activity. With 50 queries × 3 engines = 150 activities.

- **Per-engine concurrency** is capped via the engine's `concurrency_limit` (e.g., OpenAI: 10, Perplexity: 5, Google scrape: 3).
- **Cross-engine concurrency** is unlimited; we want them running in parallel.
- Temporal handles activity queuing; we use an activity option `task_queue=engine_key` so each engine's adapter runs only on workers configured for it.

### 7.4 Activity retry policies

| Failure mode | Retry policy | Max attempts |
|---|---|---|
| Engine rate-limited | Exponential backoff (1s, 2s, 4s, 8s, 16s) | 5 |
| Engine timeout | Linear backoff (5s) | 3 |
| Engine 5xx error | Exponential backoff | 4 |
| Engine 4xx (auth, malformed) | No retry; fail fast | 1 |
| Network error | Exponential backoff | 4 |
| Citation detection error (bug) | No retry; fail fast; alert | 1 |
| Budget exceeded | No retry; mark skipped | 1 |

After max attempts, the QueryExecution is marked `failed` with an error code. The workflow continues; failures contribute to engine health metrics.

### 7.5 Partial completion handling (HLD risk R2)

After all fan-out activities complete (success, failure, or skipped), the aggregator computes:

- `total_queries`, `successful_queries`, `failed_queries`
- Per-engine success rate
- `completeness_pct = successful_queries / total_queries`

Then:
- If `completeness_pct >= 0.95`: status = `completed`
- If `completeness_pct >= 0.60`: status = `partial`, and the report explicitly states which engines were not fully covered
- If `completeness_pct < 0.60`: status = `failed`. No report generated; an alert is raised; a queued retry is scheduled for healthy engines only.

### 7.6 Timeouts

| Timeout | Value | Rationale |
|---|---|---|
| Workflow total | 30 min | Hard ceiling; well above expected p99 |
| Single probe activity | 90s | Generous for slow scrapes |
| Aggregator activity | 60s | Database-heavy; not engine-bound |
| Workflow heartbeat | 30s | Detects stalled workers |

---

## 8. AI Visibility Score Computation

A single number, 0–100, that summarises a business's GEO standing.

### 8.1 Formula

```
For each engine e in {engines covered in this audit}:
    queries_total = number of queries probed on engine e
    queries_cited = number of queries where business was cited (positive or neutral polarity)
    queries_negative = number where polarity was negative
    
    engine_score_e = ((queries_cited - 0.5 * queries_negative) / queries_total) * 100
    # negative citations count half as much, because they're worse than absence

audit_score = weighted_average(engine_score_e, weight_e)
# weights default to equal across engines; future per-engine importance possible
```

### 8.2 Properties

- **Bounded:** [0, 100] always.
- **Linear and explainable:** every customer can be told exactly why their score is what it is.
- **Stable to engine outage:** if an engine wasn't covered (due to health), it's not in the average. Score is computed on healthy engines only, and `completeness_pct` is reported alongside.
- **Versioned:** the score-computation function has a version, recorded on the AuditRun.

### 8.3 Confidence bands

A score from 50 queries across 3 engines has different statistical confidence than a score from 20 queries across 1 engine. The score is annotated with a `confidence_band`:
- `high`: ≥40 successful queries across ≥2 engines
- `medium`: ≥20 successful queries across ≥1 engine
- `low`: <20 successful queries

Low-confidence scores still show but are visually de-emphasised in the report and exclude the trend line.

---

## 9. Database Schema (additions to Phase 1)

Phase 2 adds the following tables. All carry `tenant_id` and have RLS policies modelled on Phase 1's pattern.

```sql
-- ========================
-- Query templates
-- ========================

CREATE TABLE query_template_sets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    description TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    is_default BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deprecated_at TIMESTAMPTZ
);

CREATE TABLE query_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_set_id UUID NOT NULL REFERENCES query_template_sets(id),
    category_id UUID REFERENCES categories(id),
    subcategory_id UUID REFERENCES categories(id),
    locale TEXT NOT NULL DEFAULT 'en-IN',
    template_text TEXT NOT NULL,
    variables_required TEXT[] NOT NULL,
    intent_type TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    active BOOLEAN NOT NULL DEFAULT true,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX query_templates_set_idx ON query_templates(template_set_id) WHERE active = true;
CREATE INDEX query_templates_category_idx ON query_templates(category_id, subcategory_id);

-- ========================
-- Engine descriptors
-- ========================

CREATE TYPE engine_health AS ENUM ('healthy', 'degraded', 'unhealthy', 'paused');

CREATE TABLE engine_descriptors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    engine_key TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    adapter_class TEXT NOT NULL,
    access_method TEXT NOT NULL,
    supported_locales TEXT[] NOT NULL DEFAULT '{"en-IN"}',
    cost_per_call_inr NUMERIC(10,4) NOT NULL,
    rate_limit_per_minute INTEGER NOT NULL,
    concurrency_limit INTEGER NOT NULL DEFAULT 5,
    timeout_seconds INTEGER NOT NULL DEFAULT 30,
    health_status engine_health NOT NULL DEFAULT 'healthy',
    health_last_checked_at TIMESTAMPTZ,
    active BOOLEAN NOT NULL DEFAULT true,
    config_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ========================
-- Audit runs and executions
-- ========================

CREATE TYPE audit_status AS ENUM ('pending', 'running', 'partial', 'completed', 'failed');
CREATE TYPE audit_trigger AS ENUM ('free_audit', 'initial', 'weekly', 'manual', 'redetection', 'api');
CREATE TYPE query_execution_status AS ENUM ('pending', 'in_flight', 'succeeded', 'failed', 'skipped');

CREATE TABLE audit_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL REFERENCES businesses(id),
    trigger audit_trigger NOT NULL,
    status audit_status NOT NULL DEFAULT 'pending',
    algorithm_version TEXT NOT NULL,
    template_set_id UUID NOT NULL REFERENCES query_template_sets(id),
    score_computation_version TEXT NOT NULL,
    workflow_id TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    total_queries INTEGER,
    total_engines INTEGER,
    successful_engines INTEGER,
    failed_engines INTEGER,
    completeness_pct REAL,
    total_cost_inr NUMERIC(10,2),
    ai_visibility_score REAL,
    confidence_band TEXT,
    error_summary JSONB,
    redetection_of_audit_run_id UUID REFERENCES audit_runs(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_runs_business_idx ON audit_runs(business_id, created_at DESC);
CREATE INDEX audit_runs_tenant_idx ON audit_runs(tenant_id, created_at DESC);
CREATE INDEX audit_runs_status_idx ON audit_runs(status) WHERE status IN ('pending','running');

CREATE TABLE query_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL,
    audit_run_id UUID NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
    query_template_id UUID NOT NULL REFERENCES query_templates(id),
    filled_query_text TEXT NOT NULL,
    engine_key TEXT NOT NULL,
    status query_execution_status NOT NULL DEFAULT 'pending',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    raw_response_gcs_uri TEXT,
    raw_response_truncated TEXT,  -- first 4KB cached for fast access
    response_latency_ms INTEGER,
    cost_inr NUMERIC(10,4),
    error_code TEXT,
    error_detail TEXT,
    executed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (audit_run_id, query_template_id, engine_key)
);
CREATE INDEX query_executions_audit_idx ON query_executions(audit_run_id);
CREATE INDEX query_executions_engine_status_idx ON query_executions(engine_key, status, created_at DESC);

CREATE TYPE citation_match_type AS ENUM (
    'exact_name', 'alias', 'phone', 'website', 'address', 'fuzzy_name', 'composite'
);
CREATE TYPE citation_polarity AS ENUM ('positive', 'neutral', 'negative');

CREATE TABLE citations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL,
    audit_run_id UUID NOT NULL,
    query_execution_id UUID NOT NULL REFERENCES query_executions(id) ON DELETE CASCADE,
    match_type citation_match_type NOT NULL,
    confidence REAL NOT NULL,
    snippet TEXT NOT NULL,
    snippet_start_pos INTEGER,
    polarity citation_polarity NOT NULL,
    corroborating_signals TEXT[] NOT NULL DEFAULT '{}',
    algorithm_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX citations_audit_run_idx ON citations(audit_run_id);
CREATE INDEX citations_business_polarity_idx ON citations(business_id, polarity);

CREATE TABLE competitor_observations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL,
    audit_run_id UUID NOT NULL,
    query_execution_id UUID NOT NULL,
    competitor_name TEXT NOT NULL,
    competitor_name_normalized TEXT NOT NULL,
    competitor_signals JSONB NOT NULL DEFAULT '{}',
    confidence REAL NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX competitor_observations_audit_idx ON competitor_observations(audit_run_id);
CREATE INDEX competitor_observations_normalized_idx ON competitor_observations(business_id, competitor_name_normalized);
```

RLS is applied to: `audit_runs`, `query_executions`, `citations`, `competitor_observations`. Not under RLS (shared reference data): `query_template_sets`, `query_templates`, `engine_descriptors`.

---

## 10. Self-Review

### Pass 1

| # | Severity | Finding | Where |
|---|---|---|---|
| H1 | **High** | The CitationDetector treats response text as a flat string, but engine responses may include structured citations (Perplexity returns URLs alongside text). Failing to use those structured signals is a precision loss. | §4.2, §6 |
| H2 | **High** | The polarity detector is rule-based with a small lexicon. On real Indian-English responses, it will be unreliable. We need a quality baseline before this goes live. | §6.4 |
| H3 | **High** | The fan-out concurrency model in §7.3 has 150 activities per audit. At target scale (500 customers × 4 audits/month avg = 2000 audits = 300K activities/month) Temporal Cloud cost may spike. Need a cost projection or batching strategy. | §7.3 |
| H4 | **High** | We persist `raw_response_truncated` (first 4KB) in PostgreSQL but the full text in GCS. The detector runs against the full text. Re-detection therefore requires reading from GCS for every QueryExecution. At 300K/month, GCS read costs add up. Need a caching strategy or accept the cost. | §3.1 QueryExecution |
| M1 | Medium | Engine adapters reference cost numbers (₹0.15, ₹0.30, ₹0.80) but those are quoted in 2026 pricing. If a provider changes pricing, our cost ledger is wrong. Source of truth for cost? | §4.2 |
| M2 | Medium | `name_uniqueness_score` is described as "computed by a separate process" but the process is not specified. When is it run? On business creation? On every audit? | §6.3 |
| M3 | Medium | The `business_competitors` rollup writes from the Audit module to a Phase-1 table owned by the Business Profile module. This violates the "no module writes another module's tables" rule from the HLD. | §3.1 CompetitorObservation, §7.2 |
| M4 | Medium | Query generation can produce duplicates if two templates yield the same filled text after variable substitution. Need explicit deduplication. | §5.1 |
| M5 | Medium | Engine timeouts (90s per probe) plus retries (up to 5 attempts) means a single bad engine can extend an audit to >7 min, blowing the 5-min p95 target. | §7.4, §7.6 |
| M6 | Medium | Free audit creates a trial business; what happens to the *raw responses* archived in GCS when the trial is deleted (per Phase 1 §8)? DPDP requires erasure. | Cross-phase |
| L1 | Low | `audit_runs.redetection_of_audit_run_id` is a forward FK to a row that may be deleted under right-to-erasure. Need ON DELETE behaviour spec. | §9 |

Four highs and six mediums. Iterating.

### Pass 2 (resolutions)

**H1 (structured engine signals):** The `EngineResponse` value object is extended with an optional `structured_citations: list[StructuredCitation]` field. Adapters that have access to such data (Perplexity, future Google AI Overviews with citation chips) populate it. The CitationDetector consumes structured citations as a high-confidence signal — a citation URL matching the business's website is an immediate `website` match at confidence 0.99, bypassing fuzzy matching. The interface change is backwards-compatible (default empty list).

**H2 (polarity baseline):** Resolved by adding a Phase 2 deliverable: build a labelled evaluation set of 500 (response, business) pairs from real engine outputs, hand-label polarity, run the rule-based detector against it, accept only if **precision ≥ 0.85 for the "negative" class** (false-positive negatives are worse than missed negatives — accusing someone of a bad mention they don't have is worse than missing one). If we don't hit 0.85, ship with polarity disabled (all citations marked `neutral`) and treat as Phase 3 work using a small ML classifier. Acceptance criterion added to §10.5.

**H3 (Temporal cost at scale):** Computed: Temporal Cloud charges on actions. 150 activities × 2000 audits/month = 300K actions/month. At Temporal Cloud public pricing this is ~$60–100/month. Not a blocker. **However**, we batch the per-(query, engine) activities into per-engine batches of up to 10 queries each, with the batched activity calling the adapter sequentially within its quota. This reduces activity count by ~10x without losing the parallelism (multiple batches still run concurrently). New count: ~15 activities per audit × 2000 = 30K/month. Comfortably under any plausible cost cap. Implementation: the workflow fans out one activity per (engine, query_batch) instead of per (engine, query). Activity error handling becomes per-batch — partial batch success is reported back as a list of QueryExecutionResults.

**H4 (GCS read costs for re-detection):** Re-detection workflows are infrequent and operator-triggered. Each re-detection of an AuditRun reads ~50 GCS objects. At MVP scale (a few re-detections per week) this is sub-₹100/month — negligible. We accept the cost. For the *common* case (running the detector once during the original audit), the response is held in memory by the worker and written to GCS post-detection, so there's zero GCS read cost on the hot path.

**M1 (cost source of truth):** `engine_descriptors.cost_per_call_inr` is the *budget assumption*, updated by operators when provider pricing changes. The *actual cost* per call is computed by the gateway at call time using token counts (for LLM) or proxy bandwidth (for scrape), and recorded on each QueryExecution. Aggregated, these give us real cost; the descriptor cost is only used for pre-flight budget checks.

**M2 (name_uniqueness_score lifecycle):** Specified: the score is computed (a) on Business creation, (b) when the business's `canonical_name` or aliases change, and (c) on a nightly job that recomputes for any business whose corpus has changed materially. The computation is a Python utility in the Business Profile module that takes the name + corpus statistics from a shared word-frequency table (populated separately). Phase 2 ships with a simple corpus from Indian business directory data; Phase 4+ can improve.

**M3 (cross-module write):** Resolved by inverting the dependency. The Audit module emits a domain event `CompetitorsObserved(audit_run_id, observations: list[CompetitorObservationDTO])`. The Business Profile module subscribes to this event and is the one that upserts into `business_competitors`. Audit owns `competitor_observations` (its discovery records); Business Profile owns `business_competitors` (the durable rollup). Module boundary preserved.

**M4 (query deduplication):** Added explicit step in QueryGenerator: after variable substitution, queries are deduplicated by their normalised text (lowercased, whitespace-collapsed). Templates that would generate duplicates are logged as `template_collision` for operator review.

**M5 (audit p95 latency under bad-engine conditions):** Two-part fix:
- Aggressive engine timeout: per-engine `timeout_seconds` (in `engine_descriptors`) is enforced at the activity level. If exceeded, the activity fails immediately with `engine_timeout`. With Google scrape timeout = 30s and 4 retries, worst-case = ~2 min per probe.
- **Circuit breaker:** if an engine's failure rate over the last 10 minutes exceeds 50%, new probes to that engine in active workflows are immediately marked `skipped` rather than attempted. This prevents one bad engine from pinning slow audits open. Documented in §4.3.

**M6 (trial cleanup of GCS responses):** The `DeleteBusinessWorkflow` (introduced in Phase 1, extended in Phase 2) includes a step that:
1. Reads all `query_executions` for the business
2. Constructs the GCS URI list
3. Deletes the GCS objects
4. Marks `raw_response_gcs_uri = NULL` on the executions before the row is hard-deleted
Trial businesses share this workflow; the trial-expiry cron triggers `DeleteBusinessWorkflow` for each expired trial.

**L1 (FK ON DELETE behaviour):** `redetection_of_audit_run_id` uses `ON DELETE SET NULL`. Lineage is best-effort; if the source audit is purged, the redetection retains its data but loses the lineage pointer. Acceptable for an analytics relationship.

### Pass 3

Re-review after Pass 2 resolutions:

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M7 | Medium | The Pass 2 H3 batching introduces "partial batch success." We need to specify: if a 10-query batch has 3 failures and 7 successes, are those 3 retried individually, retried as a sub-batch, or marked failed and the audit continues with 7? | Specified: failures within a batch are retried as individual single-query activities (escalation pattern). Failed individual retries are marked `failed` and contribute to engine health. The audit waits for both batch and escalated activities to complete before aggregation. |
| M8 | Medium | The Pass 2 M3 event-driven cross-module write means competitor rollup is eventually consistent. If an AuditRun completes and a user looks at competitor leaderboard before the event is processed, they see stale data. | Specified: the rollup is processed within the same workflow (an in-workflow activity that calls Business Profile's public service method, which internally handles the upsert). This is technically a *service call*, not a direct table write — the upsert is owned by Business Profile. The event is also emitted for other subscribers (e.g., Notifications). Synchronous from the user's perspective. |
| L2 | Low | `raw_response_truncated` (4KB) duplicates data that's also in GCS. If the truncation strategy is too aggressive, mid-response citations may not be displayable in the report without a GCS read. | Acceptable: 4KB covers ~600 words, which is longer than every observed AI engine response in benchmark testing. Report rendering uses the truncated text; rare exceptions fetch from GCS. |

**M7 and M8 resolved** in this pass.

No remaining H or M findings. **Self-review passes.**

---

## 11. Test Strategy

### 11.1 Unit tests

- Citation detector: golden-file tests for each stage, with crafted inputs.
- Name uniqueness scorer: monotonicity tests (more common tokens → lower score).
- Score formula: boundary tests (zero citations → 0; all citations → 100; with negatives → reduced).
- Engine adapter mocks: each adapter has a mocked transport for unit tests.

### 11.2 Integration tests

- End-to-end audit workflow against testcontainers Postgres + Temporal devserver + recorded engine responses (replayed from fixture cassettes).
- Engine adapter integration tests against real APIs in a dedicated test account, run nightly (not on every PR — too slow and rate-limited).

### 11.3 The Citation Detection Evaluation Harness

The single most important quality safeguard in Phase 2.

- A labelled dataset of 500 (response, business_identity, expected_citation) tuples.
- The harness runs the current detector against the entire dataset and reports:
  - Precision, recall, F1 by match_type
  - False-positive examples (citations declared where label says no)
  - False-negative examples (label says yes; detector said no)
- The harness runs on every PR that touches `audit/citation_detector/` and fails the build if precision or recall drops below the labelled-set floor (P≥0.90, R≥0.85, per NF3/NF4).
- The dataset grows over time as production false-positives and false-negatives are added (with human review).

### 11.4 Performance tests

- 1 audit, full fan-out (50 queries × 3 engines): end-to-end <5 min p95.
- 10 concurrent audits: no engine rate-limit violations.
- Citation detection on 4KB response: <50ms.

### 11.5 Engine adapter chaos tests

- Test each adapter against: 500 response, 503 response, timeout, malformed response, rate-limit response, partial response (connection closed mid-stream). Verify each maps to the right error code with the right retry semantics.

### 11.6 Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| AC1 | A free audit for a real Bengaluru CA firm produces a report with at least 80% completeness in <5 min. | End-to-end manual + monitoring |
| AC2 | Re-running the same audit (same inputs) produces an identical AIVisibilityScore. | Deterministic test |
| AC3 | If OpenAI is marked unhealthy, audits run with partial coverage on the other two engines, no errors. | Integration test (chaos) |
| AC4 | False positives on a labelled set of 100 production-like queries: ≤10. | Evaluation harness |
| AC5 | Cost per audit at MVP rates ≤ ₹40 measured over 50 audits. | Cost dashboard |
| AC6 | A redetection of an old AuditRun (same algorithm) produces identical citations. | Reproducibility test |
| AC7 | Polarity detector hits P≥0.85 on the labelled set. If not, polarity ships disabled. | Evaluation harness |

---

## 12. Implementation Tasks (sprint-ready)

Estimated: 2 backend engineers + 1 ML/NLP engineer × 4 sprints (8 weeks).

### Sprint 1 — Engine Adapter Foundation
- Engine adapter protocol + EngineRegistry + descriptor table (2d)
- LLMGateway + ProxyGateway with cost metering (3d)
- OpenAIChatAdapter (1d)
- PerplexityAdapter (1d)
- Engine health monitor + circuit breaker (2d)
- Engine adapter chaos test suite (2d)

### Sprint 2 — Query Templates + Audit Workflow Skeleton
- query_template_sets + query_templates schema + seeds (1d)
- QueryGenerator with variable substitution and deduplication (2d)
- AuditWorkflow skeleton (1d)
- Fan-out activity batching (Pass 2 H3 resolution) (2d)
- AuditRun + QueryExecution schemas (1d)
- BusinessIdentity resolution service (1d)
- Workflow integration test (1d)
- Per-business cost budget enforcement (1d)

### Sprint 3 — Citation Detection
- CitationDetector stages 1–4 (exact, alias, phone, website) (3d)
- Stage 5 (address fingerprint) (1d)
- Stage 6 (fuzzy name with corroboration) (2d)
- name_uniqueness_score computation (1d)
- Polarity detector v1 (rule-based) (2d)
- Citation table + persistence (1d)
- Evaluation harness + labelled set v1 (50 examples) (2d)

### Sprint 4 — Google Scrape Adapter + Polish
- GoogleAIOverviewsScrapeAdapter with Playwright + proxy pool (4d)
- Scrape selector resilience + multi-selector strategy (1d)
- Score computation + confidence bands (1d)
- CompetitorObservation + rollup via domain event (2d)
- Redetection workflow (1d)
- Evaluation harness expansion to 500 examples (3d)
- Operational dashboards (engine health, audit throughput) (1d)
- Acceptance criteria verification (2d)

### Phase 2 exit criteria
- All §11.6 acceptance criteria pass.
- Citation detector precision ≥ 0.90, recall ≥ 0.85 on labelled set.
- 100 audits run successfully end-to-end on real Bengaluru businesses.
- Engine adapter chaos tests green.
- Operational dashboards in place; on-call rotation can investigate engine failures unaided.

---

## 13. Handoff to Phase 3

Phase 3 (Reporting & Free Audit Experience) consumes from this phase:
- `AuditRun` reads — score, citations, competitor observations, completeness — to render reports.
- The `AuditRunCompleted` domain event — Phase 3 subscribes to trigger PDF generation + email.
- The per-AuditRun query/engine breakdown — Phase 3 builds the "Top Winning / Lost Queries" sections from this.
- `BusinessCompetitor` (Phase 1 table, populated by Phase 2 rollup) — Phase 3 renders the competitor leaderboard.

The contract between Phase 2 and Phase 3 is the `AuditRun` aggregate's read interface. Phase 2 ships the producer; Phase 3 ships the consumers.

---

*CitedBy Phase 2 Design v1.0 | Confidential | May 2026*
*Next: Phase 3 — Reporting & Free Audit Experience*
