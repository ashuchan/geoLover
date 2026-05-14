# CitedBy — Phase 4 Design
## Content Generation & LLM Gateway
**Version:** 1.0
**Status:** Approved for implementation
**Date:** May 2026
**Author:** CTO, CitedBy
**Parent document:** `CitedBy_HLD_v1.md`
**Modules covered:** Content Generation (#4), plus the cross-cutting LLM Gateway used by all modules

---

## 1. Phase Overview

### 1.1 Why this is Phase 4

Phase 3 ships the audit and its report. The report tells a business they are not cited. **Phase 4 builds what we do about it.** Without Phase 4, the product is diagnostic-only — useful, but not transformative. Phase 4 is the bridge from "you have a problem" to "we are solving it." It is also where the bulk of our variable cost lives, which is why the LLM Gateway is a first-class architectural concern, not an implementation detail.

### 1.2 What this phase delivers

By the end of Phase 4:

- An **LLM Gateway** is the single chokepoint for every model call across the platform. It implements provider abstraction (Claude primary, GPT-4 fallback, static-template last resort), cost metering, caching, validation, and per-tenant budget enforcement.
- A **Prompt Store** holds versioned prompt definitions in the database. Engineers and product can ship new prompt versions without code deploys; experiments are first-class (A/B cohorts).
- A **Content Brief Service** consumes the output of an `AuditRun` (the "Top 3 Quick Wins") and generates structured content briefs covering four PRD content types: Direct Answer Pages, FAQ Clusters, Comparison Pages, and Entity Summaries.
- A **Content Asset model** persists every generated version, with a state machine (draft → in_review → approved → rejected → superseded → published).
- An **Approval workflow** routes drafts to the right reviewer based on tenant type and configurable policy.
- **Schema.org JSON-LD** generation accompanies every content asset that has an associated business profile.
- **Cost ceilings** are live: per-business monthly LLM budgets are enforced; soft-warn at 80%, hard-block discretionary content generation at 100%.
- The Content Generation workflow is a **first-class Temporal workflow**, fully durable and resumable.

### 1.3 What this phase does NOT deliver

- Publishing of approved content (Phase 5).
- Indian-language (Hindi/Kannada/Tamil) content generation. The prompt store and gateway accept a `locale` parameter, but the only locale shipped is `en-IN`.
- Voice/audio-optimised content (Phase 2 extension; deferred).
- Image generation (no plans; not needed for citation).
- Real-time streaming UX. Generation is batch — the user submits a request, gets a notification when ready (typically 30–120 seconds).
- Editor UI for in-place content editing (Phase 7 + Phase 8).

---

## 2. Requirements

### 2.1 Functional requirements

| # | Requirement | Source |
|---|---|---|
| F1 | Given an AuditRun with at least 3 "lost queries", the system generates 4 content briefs per the PRD-specified content types. | PRD §3.1 Module 2 |
| F2 | Each brief is reviewed and approved by a designated reviewer before becoming eligible for publishing. | PRD §3.1 Module 2 |
| F3 | Approval flow is configurable per tenant: `agency_only` (default), `business_only`, `agency_then_business`. | Phase 1 HLD self-review (R7) |
| F4 | Every brief is associated with `source_audit_run_id` and the specific lost queries that inspired it. | HLD §15 H2 |
| F5 | LLM provider failure (rate limit, timeout, content policy block) falls back to the secondary provider, then to a static template. | HLD §10.2 |
| F6 | Per-business monthly LLM spend is tracked; soft warning at 80%, hard block on new content generation at 100%. | HLD §10.3 |
| F7 | Prompts are versioned; multiple active versions can coexist for experimentation (A/B cohorts via PostHog feature flag). | HLD §15 H1 |
| F8 | Content output is validated against a schema (correct sections, length bounds, no obvious hallucinations on factual business attributes). | F3 of Phase 4 quality bar |
| F9 | Generated content includes Schema.org JSON-LD where applicable. | PRD §3.1 Module 2.1 |
| F10 | Rejected briefs may be regenerated with reviewer feedback as an additional input. | UX requirement |
| F11 | Audit-log of every LLM call: prompt key + version, model, tokens, cost, business_id, tenant_id, outcome. | Compliance + cost analysis |
| F12 | Content is locale-tagged; the architecture supports `hi-IN`, `kn-IN`, `ta-IN`, etc. (not shipped in Phase 4). | Phase 2-readiness |

### 2.2 Non-functional requirements

| # | Requirement | Target |
|---|---|---|
| NF1 | Content brief generation latency (single brief, single LLM call). | <30 seconds p95 |
| NF2 | Full 4-brief generation for an audit run. | <2 minutes p95 (parallel) |
| NF3 | LLM call success rate (after retry + fallback). | >99% |
| NF4 | LLM spend tracking error margin. | <1% vs. provider invoice |
| NF5 | Prompt version change must reach workers within. | 5 minutes |
| NF6 | Cost ceiling check latency (per-call overhead). | <50ms |
| NF7 | Cache hit ratio on deterministic prompts. | >40% over a typical week |

---

## 3. Domain Model — Detailed

### 3.1 Aggregates

#### `PromptVersion`
```
PromptVersion
├── id                       (UUID)
├── prompt_key               (string; stable identifier, e.g. 'direct_answer_page_v')
├── version                  (integer; monotonically increasing per key)
├── system_text              (text; system message)
├── user_template            (text; with {{placeholder}} substitution)
├── parameters_schema        (JSONB; validates inputs)
├── output_schema            (JSONB; validates outputs)
├── recommended_model        (string; e.g. 'claude-opus-4-7')
├── temperature              (numeric)
├── max_tokens               (integer)
├── locale                   (string; default 'en-IN')
├── active_flag              (boolean; can be activated/retired)
├── experiment_cohort        (string nullable; PostHog flag name for A/B)
├── notes                    (text; rationale for change)
├── created_by_user_id       (FK → users)
├── created_at
└── retired_at               (nullable)
```

**Invariants:**
- A given `(prompt_key, version)` is immutable once `active_flag = true`. Edits create a new version.
- For a given `prompt_key`, at most one `active_flag = true` row at a time per `locale` and `experiment_cohort`. The default cohort is `'control'`.
- Workers look up prompts at runtime; results cached for 5 minutes (NF5).

#### `ContentBrief`
```
ContentBrief
├── id                       (UUID)
├── tenant_id, business_id   (FK; tenant_id denormalised for RLS)
├── source_audit_run_id      (FK → audit_runs; HLD §15 H2)
├── source_lost_query_ids    (UUID[]; specific queries that motivated this brief)
├── brief_type               (enum: 'direct_answer_page' | 'faq_cluster' |
│                                    'comparison_page' | 'entity_summary')
├── target_query             (text; the user-intent the brief targets)
├── current_state            (enum: 'draft' | 'in_review' | 'approved' |
│                                    'rejected' | 'superseded' | 'published')
├── current_asset_id         (FK → content_assets; the active version)
├── reviewer_user_id         (FK → users, nullable)
├── approval_flow            (enum: 'agency_only' | 'business_only' | 'agency_then_business')
├── created_at, updated_at
└── deleted_at               (nullable)
```

**Invariants:**
- `tenant_id` matches the business's tenant. Enforced by trigger.
- State transitions enforced in code (state machine). Specifically:
  - `draft → in_review` (when first generation completes)
  - `in_review → approved | rejected`
  - `approved → published` (only from Phase 5 PublishWorkflow)
  - `rejected → in_review` (after regeneration with feedback)
  - Any state → `superseded` (when a new brief for the same query is generated)

#### `ContentAsset`
```
ContentAsset
├── id                       (UUID)
├── tenant_id, business_id   (FK)
├── brief_id                 (FK → content_briefs)
├── version                  (integer; 1, 2, 3... within a brief)
├── markdown                 (text; primary content body)
├── html                     (text; rendered HTML for publish)
├── schema_jsonld            (JSONB; Schema.org structured data)
├── prompt_version_id        (FK → prompt_versions)
├── llm_call_id              (FK → llm_calls; for traceability)
├── validation_status        (enum: 'pending' | 'passed' | 'failed')
├── validation_findings      (JSONB; details of any check failures)
├── reviewer_notes           (text; from rejection or approval)
├── created_at
```

**Invariants:**
- `(brief_id, version)` is unique.
- `version` is monotonically increasing per brief.
- A `ContentAsset` is immutable once persisted — corrections produce new versions.

#### `LLMCall`
```
LLMCall
├── id                       (UUID)
├── tenant_id, business_id   (FK; both denormalised for budget queries)
├── purpose                  (enum: 'content_brief_gen' | 'audit_quick_wins' | 'translation' | 'eval' | ...)
├── provider                 (enum: 'anthropic' | 'openai' | 'fallback_static')
├── model                    (string)
├── prompt_key, prompt_version_id
├── input_tokens, output_tokens
├── cost_inr                 (numeric, denormalised at call time)
├── duration_ms
├── status                   (enum: 'success' | 'error_rate_limit' | 'error_safety' |
│                                    'error_timeout' | 'error_provider' | 'cache_hit')
├── cache_key                (text nullable; for deterministic call cache)
├── workflow_id              (text nullable; Temporal workflow that initiated)
├── created_at
```

**Used for:** cost analysis, budget enforcement, audit log (F11), eval harness reproducibility.

#### `UsageCounter` (lightweight summary table)
```
UsageCounter
├── tenant_id, business_id, period (YYYY-MM)
├── llm_calls_count
├── llm_cost_inr
├── content_briefs_generated
├── updated_at
├── PRIMARY KEY (tenant_id, business_id, period)
```

Updated incrementally on every LLMCall write. Read by budget pre-check. Eventually consistent with `LLMCall` rows; reconciled nightly.

### 3.2 Relationship overview

```
PromptVersion 1───N LLMCall 1───1 ContentAsset N───1 ContentBrief
                              │
                              └─ (purpose='audit_quick_wins') used by Phase 3
AuditRun 1───N ContentBrief (via source_audit_run_id)
Business 1───N ContentBrief
ContentBrief 1───N ContentAsset (versioned)
```

---

## 4. The LLM Gateway — the system's most important seam

### 4.1 Why the gateway exists

Every LLM call in CitedBy goes through one place. This is non-negotiable. The reasons compound:

1. **Cost governance.** Without a chokepoint, costs are unbounded and unattributable.
2. **Provider portability.** Anthropic, OpenAI, Sarvam, Krutrim, and whoever wins Q3 2026 — each becomes an adapter, not a code change in every caller.
3. **Caching.** Deterministic prompts can return from cache. Without a chokepoint, every caller has to remember to implement this.
4. **Observability.** One place to log, trace, and meter.
5. **Safety.** One place to enforce content policy, redact PII before sending to providers, redact PII before persisting responses.
6. **Testability.** One thing to mock. Tests don't depend on Anthropic's API.

### 4.2 Public interface

```python
class LLMGateway:
    async def complete(
        self,
        *,
        prompt_key: str,
        params: dict,
        tenant_id: UUID,
        business_id: UUID | None,
        purpose: LLMPurpose,
        locale: str = "en-IN",
        idempotency_key: str | None = None,
    ) -> LLMResult:
        """
        Resolves the active PromptVersion for (prompt_key, locale, cohort).
        Validates params against parameters_schema.
        Checks per-business budget pre-call.
        Checks cache (if idempotency_key provided and prompt is cacheable).
        Calls primary provider; on retryable failure, retries; on non-retryable, falls back to secondary; on all-fail, falls back to static template.
        Validates output against output_schema.
        Records LLMCall, updates UsageCounter.
        Returns LLMResult with structured output + metadata.
        """
```

The signature is deliberately minimal. Callers do not pick the model. They do not pass system prompts. They do not handle rate limits. They request a *purpose* with *parameters* and get a result.

### 4.3 Provider abstraction

```python
class LLMProvider(Protocol):
    name: str
    
    async def call(
        self,
        *,
        system: str,
        user: str,
        model: str,
        temperature: float,
        max_tokens: int,
        timeout_s: float,
    ) -> ProviderResponse:
        """Single attempt. Raises typed exceptions for caller to classify."""
    
    def estimate_cost(self, input_tokens: int, output_tokens: int, model: str) -> Decimal: ...
```

Concrete implementations: `AnthropicProvider`, `OpenAIProvider`, `StaticTemplateProvider` (returns deterministic templated text from a registry of fallback templates).

### 4.4 Fallback chain

```
Primary attempt (Anthropic Claude)
   │
   ├─ Success → return
   ├─ RateLimit → retry with backoff (up to 3 attempts) → if still failing, treat as failure
   ├─ Timeout → retry once → if still failing, treat as failure
   ├─ SafetyBlock → DO NOT retry; classify as 'error_safety'; fall through
   ├─ AuthError | QuotaExhausted → DO NOT retry; alert ops; fall through
   │
Failure → Secondary attempt (OpenAI GPT-4)
   │
   ├─ Success → return (with fallback=true marker)
   ├─ Same classes of failure → fall through
   │
Failure → Static template
   │
   └─ Always returns a baseline output. Caller knows quality is degraded (see §4.6).
```

The static template provider exists because **the workflow must complete**. A best-effort baseline output is better than a hard failure that halts the workflow. The output is marked `provider='fallback_static'` and excluded from "showcase" metrics; reviewers see the marker and know to either regenerate later or replace manually.

### 4.5 Budget enforcement

Before every LLM call:

```
1. Read UsageCounter for (tenant_id, business_id, current_period).
2. Add estimated cost (from PromptVersion's recommended_model + max_tokens).
3. If estimated_total > plan.monthly_llm_budget_inr:
     - If purpose is 'audit_*': allow (audits are core, predictable cost)
     - Else: raise BudgetExceeded; caller surfaces "quota stop" state
4. If estimated_total > 0.8 * budget and no soft-warn already sent this period:
     - Emit `QuotaThresholdReached(tenant_id, business_id, threshold=0.8)` event
5. Proceed.
```

The 80% threshold notification is debounced once per (tenant_id, business_id, period) to avoid spam.

`UsageCounter` is updated *post-call* with actual tokens, not estimated. This means a single rogue call can slightly overshoot the budget by one call's worth of cost. Acceptable in practice; the alternative (reserve-then-commit) doubles call latency.

### 4.6 Caching

Cacheable calls require:
- `temperature == 0` (deterministic outputs)
- `idempotency_key` provided by caller (or derived from params hash)
- Prompt version unchanged since cached entry

Cache key: `hash(prompt_key, prompt_version_id, params_canonical_json, locale)`.

Storage: Redis with 30-day TTL. Cache hits return immediately; an `LLMCall` row is still written with `status='cache_hit'` and `cost_inr=0` for analytics.

The audit-quick-wins prompt benefits most from caching: many audits over the same business with stable profiles produce identical wins. Content brief generation is less cacheable (parameters include audit-specific data).

### 4.7 PII handling on prompts and responses

**Before sending to provider:**
- Business profile fields sent in prompts are validated against an allowlist (name, category, location, services, keywords). No PII like customer phone numbers is ever in a prompt.
- If a parameter contains text from an audit (e.g., a citation snippet), it is run through a PII redactor that replaces detected emails/phones/addresses with `[REDACTED_EMAIL]` etc. This protects against the rare case where an engine response quotes a customer review with personal information.

**After receiving from provider:**
- Response is run through the same PII redactor before persistence. Findings logged.

This is the §10.5 mitigation from HLD §15 Pass 1 M1.

### 4.8 Audit logging

Every call writes an `LLMCall` row with full metadata. Sensitive fields (the actual prompt input text, the response text) are stored in GCS, not Postgres, with the `LLMCall.id` as the object key. Postgres holds only the metadata. This keeps the hot table small and the bulk content cold.

Retention: 90 days for the GCS objects (long enough for debugging and eval), then deleted. `LLMCall` metadata rows retained 7 years for billing audit.

---

## 5. The Prompt Store

### 5.1 Why prompts live in the database

Prompts are product. They are not code. Treating them as code couples prompt changes to engineering releases, which is the wrong cadence — the product team should be able to ship a prompt fix in 10 minutes, not wait for the next deploy.

But prompts are also not totally free-form text — they have:
- Required input parameters (which the calling code provides)
- Expected output schemas (which downstream code consumes)
- Cost implications (model + max_tokens)
- Locale binding

So prompts in the database, but with structure. That structure is `PromptVersion` (§3.1).

### 5.2 Prompt lifecycle

```
Author drafts new version in admin UI
   ↓
Set as 'experiment' (cohort='exp_alpha', active_flag=true) — only 10% of calls hit it via PostHog flag
   ↓
Observe metrics: cost, quality (eval harness scores), reviewer rejection rate
   ↓
If good: promote to control cohort, retire old control version
If bad: deactivate, leave for inspection
```

### 5.3 Output validation

Every prompt version ships with an `output_schema` (JSON Schema). After an LLM response is parsed (usually JSON-mode where possible), it is validated against the schema. Failures cause the call to be marked `validation_status='failed'` in the resulting `ContentAsset`; the orchestrator decides whether to regenerate or escalate.

This is one of the most underrated features. Without it, "the LLM returned garbage" is a runtime mystery; with it, the failure is structured and observable.

### 5.4 Prompt registry (Phase 4 starter set)

| `prompt_key` | Purpose | Output schema (shape) |
|---|---|---|
| `audit_quick_wins_v` | Generate top-3 actionable wins from an audit | `{wins: [{title, action, expected_impact}]}` |
| `direct_answer_page_v` | Generate a Direct Answer Page for a lost query | `{title, h1, lede, body_sections[], faq_pairs[], jsonld}` |
| `faq_cluster_v` | Generate 20 Q&A pairs around a category | `{qas: [{question, answer}]}` |
| `comparison_page_v` | Generate a "How to choose X in Y" guide | `{title, criteria[], comparison_table, jsonld}` |
| `entity_summary_v` | Generate canonical entity description for KG seeding | `{description, services[], audience, jsonld}` |
| `pii_redactor_v` | (Cheap model) PII detection on text | `{redactions: [{type, span, replacement}]}` |

`pii_redactor_v` exists because cheap-model LLMs (Haiku, GPT-4o-mini) outperform regex-based redaction on Indian addresses and names. Cost per call is fractions of a paisa.

---

## 6. Content Brief Service

### 6.1 The workflow

When `AuditRun.Completed` fires for an audit that has identified at least 3 lost queries:

```
ContentBriefGenWorkflow(audit_run_id, business_id)
   │
   ├─ Activity: Load AuditRun + Business profile + top 4 lost queries (ranked by impact)
   ├─ Activity: BudgetPreCheck (LLMGateway internal)
   ├─ For each of 4 lost queries (parallel):
   │     ├─ Choose brief_type based on query intent (transactional → direct_answer; informational → faq)
   │     ├─ Activity: GenerateBriefDraft
   │     │       → LLMGateway.complete(prompt_key=brief_type_prompt, ...)
   │     │       → Persist ContentAsset (validation_status='pending')
   │     │       → Run validators (length, schema, hallucination heuristics)
   │     │       → Update ContentAsset.validation_status
   │     ├─ Activity: PersistContentBrief (creates ContentBrief in 'in_review' state)
   ├─ Activity: NotifyReviewer (Phase 6 NotificationService)
   └─ DONE
```

The fan-out is via `asyncio.gather` within the workflow; each brief is its own activity for independent retry. A failure on one brief doesn't lose the others.

### 6.2 Validators

The validators are deliberately not "another LLM check" by default — that would be expensive and circular. They are deterministic checks:

| Validator | Check | Action on fail |
|---|---|---|
| `SchemaValidator` | Output matches `prompt_version.output_schema` | Mark `validation_status='failed'`, queue regeneration once |
| `LengthValidator` | Body within `[min, max]` chars per brief_type | Mark failed |
| `BusinessFactConsistency` | Business name, locality, services appear correctly in output (substring + fuzzy) | Mark failed |
| `NoForbiddenClaims` | Output does not contain reserved phrases ("guaranteed", "100% success", "best in the world") | Mark failed |
| `SchemaJsonLDValidator` | JSON-LD validates against Schema.org for the declared type | Warn (does not fail) |

An optional `LLMQualityCheck` (using a cheaper model) is available behind a feature flag for high-stakes content; off by default to control cost.

### 6.3 Approval workflow

Once a brief reaches `in_review`, the approval routing depends on tenant configuration:

| `approval_flow` | Who is reviewer | UI surface |
|---|---|---|
| `agency_only` (default for agency tenants) | A user with `agency_admin` or `agency_member` role | Agency portal "pending approvals" queue |
| `business_only` (default for direct tenants) | `business_owner` of the business | Business dashboard "pending approvals" |
| `agency_then_business` | Agency first, then business | Two-stage; only second-stage approval is "final" |

Approvers can:
- Approve → `current_state = 'approved'`
- Reject with notes → creates a new draft asset (regenerated by the workflow with the reviewer notes as additional input); state returns to `in_review` with the new asset

Regeneration cap: 3 per brief. After 3 rejections, the brief is parked as `rejected` and surfaced for manual intervention.

### 6.4 The Schema.org JSON-LD layer

Every brief type's prompt includes instructions to produce a valid JSON-LD block. The schema_jsonld field is stored separately from the markdown body so that:
- The publisher (Phase 5) can inject it cleanly into the publish target's `<head>` tag without parsing the markdown.
- It can be re-validated independently when Schema.org spec changes.

Phase 4 ships these JSON-LD types:
- `LocalBusiness` (for entity summaries)
- `FAQPage` (for FAQ clusters)
- `Service` (for direct answer pages about a service)
- `WebPage` with `mainEntity` references (for comparison pages)

---

## 7. Database Schema (additions to Phase 1)

### 7.1 New tables

```sql
CREATE TABLE prompt_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prompt_key TEXT NOT NULL,
    version INTEGER NOT NULL,
    system_text TEXT NOT NULL,
    user_template TEXT NOT NULL,
    parameters_schema JSONB NOT NULL,
    output_schema JSONB NOT NULL,
    recommended_model TEXT NOT NULL,
    temperature NUMERIC(3,2) NOT NULL DEFAULT 0.0,
    max_tokens INTEGER NOT NULL,
    locale TEXT NOT NULL DEFAULT 'en-IN',
    active_flag BOOLEAN NOT NULL DEFAULT false,
    experiment_cohort TEXT NOT NULL DEFAULT 'control',
    notes TEXT,
    created_by_user_id UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    retired_at TIMESTAMPTZ,
    UNIQUE (prompt_key, version)
);
CREATE UNIQUE INDEX prompt_versions_active_uniq
    ON prompt_versions(prompt_key, locale, experiment_cohort)
    WHERE active_flag = true AND retired_at IS NULL;

CREATE TYPE brief_type AS ENUM (
    'direct_answer_page', 'faq_cluster', 'comparison_page', 'entity_summary'
);
CREATE TYPE brief_state AS ENUM (
    'draft', 'in_review', 'approved', 'rejected', 'superseded', 'published'
);
CREATE TYPE approval_flow_type AS ENUM (
    'agency_only', 'business_only', 'agency_then_business'
);

CREATE TABLE content_briefs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL REFERENCES businesses(id),
    source_audit_run_id UUID NOT NULL,  -- FK to audit_runs (Phase 2 table)
    source_lost_query_ids UUID[] NOT NULL,
    brief_type brief_type NOT NULL,
    target_query TEXT NOT NULL,
    current_state brief_state NOT NULL DEFAULT 'draft',
    current_asset_id UUID,  -- FK added after asset table
    reviewer_user_id UUID REFERENCES users(id),
    approval_flow approval_flow_type NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ
);
CREATE INDEX content_briefs_business_state_idx
    ON content_briefs(business_id, current_state) WHERE deleted_at IS NULL;
CREATE INDEX content_briefs_tenant_idx ON content_briefs(tenant_id);

CREATE TABLE content_assets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL,
    brief_id UUID NOT NULL REFERENCES content_briefs(id),
    version INTEGER NOT NULL,
    markdown TEXT NOT NULL,
    html TEXT NOT NULL,
    schema_jsonld JSONB,
    prompt_version_id UUID NOT NULL REFERENCES prompt_versions(id),
    llm_call_id UUID NOT NULL,  -- FK to llm_calls
    validation_status TEXT NOT NULL DEFAULT 'pending',
    validation_findings JSONB,
    reviewer_notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (brief_id, version)
);

ALTER TABLE content_briefs
    ADD CONSTRAINT content_briefs_current_asset_fk
    FOREIGN KEY (current_asset_id) REFERENCES content_assets(id);

CREATE TYPE llm_purpose AS ENUM (
    'content_brief_gen', 'audit_quick_wins', 'pii_redaction',
    'translation', 'eval', 'other'
);

CREATE TABLE llm_calls (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    business_id UUID,
    purpose llm_purpose NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_key TEXT NOT NULL,
    prompt_version_id UUID REFERENCES prompt_versions(id),
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost_inr NUMERIC(10, 4) NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    status TEXT NOT NULL,
    cache_key TEXT,
    workflow_id TEXT,
    error_class TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX llm_calls_tenant_period_idx
    ON llm_calls(tenant_id, business_id, date_trunc('month', created_at));
CREATE INDEX llm_calls_workflow_idx ON llm_calls(workflow_id) WHERE workflow_id IS NOT NULL;
CREATE INDEX llm_calls_cache_idx ON llm_calls(cache_key) WHERE cache_key IS NOT NULL;

CREATE TABLE usage_counters (
    tenant_id UUID NOT NULL,
    business_id UUID NOT NULL,
    period CHAR(7) NOT NULL,  -- 'YYYY-MM'
    llm_calls_count INTEGER NOT NULL DEFAULT 0,
    llm_cost_inr NUMERIC(12, 4) NOT NULL DEFAULT 0,
    content_briefs_generated INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, business_id, period)
);
```

### 7.2 RLS

RLS applied to: `content_briefs`, `content_assets`, `llm_calls`, `usage_counters`. Same template as Phase 1.

**Not under RLS:** `prompt_versions` — prompts are platform-wide, not tenant-scoped. Read access for all authenticated services; write access for `platform_admin` only.

---

## 8. Self-Review

### Pass 1

| # | Severity | Finding | Where |
|---|---|---|---|
| H1 | **High** | The static-template fallback (§4.4) produces baseline content of unknown quality. If it's bad enough to embarrass us, customers will lose trust faster than the LLM failure would have. We need a quality gate: the static fallback must produce *something defensible* or refuse to produce. | §4.4 |
| H2 | **High** | The output_schema validator (§5.3) is described, but LLMs occasionally return valid-JSON-but-wrong-data (e.g., `{"title": "TODO"}`). The schema alone won't catch that. | §6.2 |
| H3 | **High** | The Approval Workflow re-uses `business_owner (in agency)` from Phase 1. But Phase 1 (M1 resolution) noted that scoped members' permissions are read on every request — so if the agency removes the business from scope mid-approval, the next click could 403. Need explicit behaviour. | §6.3 |
| M1 | Medium | The "max 3 regenerations per brief" cap is a number pulled from intuition. If LLM quality is variable in the early weeks, this could be too tight. | §6.3 |
| M2 | Medium | Budget enforcement (§4.5) happens pre-call, but post-call writes can race. Two parallel calls could both pass the 80% check, then both exceed. | §4.5 |
| M3 | Medium | Prompt versions cached for 5 minutes. But what about a critical safety hotfix — a prompt change that *must* propagate immediately (e.g., produces unsafe output)? | §3.1 invariants, §4.2 |
| M4 | Medium | The PII redactor (§4.7) uses an LLM. If the LLM itself fails, our PII safety net fails open. | §4.7 |
| M5 | Medium | The static-template fallback content (§4.4) is described as marked but the reviewer-side UX is undefined. How does Priya (agency admin) know "this draft is degraded"? | §4.4, §6.3 |
| L1 | Low | `BusinessFactConsistency` validator does substring matching for business name. What about a name that's a common phrase (e.g., "City Clinic" — substring matches half the corpus)? | §6.2 |

Three highs and four mediums. Iterating.

### Pass 2 (resolutions)

**H1 (static fallback quality):** The static-template fallback is constrained to produce a *minimal but professional* placeholder, not a fully composed page. Concretely:
- For `direct_answer_page`: a 3-paragraph stub with the business name, locality, category, and a CTA. Editor-rendered with a banner "This draft was generated with a basic template due to an AI service issue. We recommend regenerating before publishing."
- For `faq_cluster`: 5 generic Q&A pairs about the category, with the business name substituted.
- For `comparison_page`: a structured "things to consider when choosing X in Y" outline with empty rows for the business to fill.
- For `entity_summary`: a templated `LocalBusiness` JSON-LD with the profile data; no prose body.

The fallback never publishes automatically (state stays `draft`, not `in_review`). The fallback is genuinely a last resort that produces a starting point for a human, not a finished artifact. Documented in §4.4.

**H2 (LLM returns plausible-but-wrong):** Added validator `PlausibleContentValidator`:
- Asserts critical placeholder phrases are not present: `"TODO"`, `"PLACEHOLDER"`, `"[FILL IN]"`, `"Example text"`, `"Lorem ipsum"`.
- Asserts business name appears in body (not only metadata).
- Asserts at least one location term (city or locality) appears.
- Asserts content density: ratio of unique tokens to total tokens > 0.35 (catches repetitive padding).

These are heuristic but cheap and catch the obvious failures. False-positive rate documented during eval.

**H3 (scope change mid-approval):** Approval action handler does an authorization check immediately before applying state change, not at page-load. If scope was revoked, the user sees a friendly error: "Your access to this business has been removed. Please contact your administrator." The brief remains in `in_review`. Any other agency admin can still approve.

**M1 (regeneration cap):** Cap raised to 5 and made plan-configurable. The number is in `plans` table, not hardcoded. Per-tenant override possible for high-tier customers.

**M2 (budget race):** Post-call writes use a serialisable upsert with `FOR UPDATE` on the `usage_counters` row. Pre-call check + post-call update are not atomic; small overshoot still possible (one call's cost), but the *budget is enforced* such that the second call sees the first call's spend if it lands first. For stricter atomicity we'd need pre-call reservation (debit-then-commit), but the operational cost (double latency, reservation cleanup on failure) isn't justified for our scale.

We accept up to one in-flight call's worth of overshoot. For a 4-brief parallel generation, max overshoot is 3 briefs' cost. Documented; tracked in observability.

**M3 (prompt hotfix propagation):** Added an admin endpoint `POST /api/v1/admin/prompts/invalidate-cache`. When a `prompt_version.active_flag` change requires immediate propagation, the admin invokes this. It broadcasts a Redis pub/sub `prompts.invalidated` event; all workers subscribe and clear their local prompt cache on receipt. Total propagation time: seconds, not 5 minutes.

**M4 (PII redactor LLM failure):** Two-layer redaction:
1. **Regex layer** runs first, always. Catches obvious patterns (email, phone E.164, Aadhaar-like, PAN-like). Fast, reliable, no LLM dependency.
2. **LLM layer** runs second, additively. Catches what regex misses (names in context, addresses without postcodes).

If LLM redaction fails, only regex redaction applies. The result is *less thorough* but never absent. Documented in §4.7.

**M5 (degraded-content UX):** Reviewer UI shows a prominent banner on any `ContentAsset` where `LLMCall.provider = 'fallback_static'`: "⚠ This draft was generated with a basic template due to an AI service issue. We recommend regenerating before publishing." Also surfaced in the approvals queue listing.

**L1 (common-name substring matching):** `BusinessFactConsistency` uses the business's `name_normalized` for primary match, but if the business has `identity_uniqueness_score < 0.5` (low-uniqueness names — Phase 1 schema), it additionally requires the locality or website domain to appear. Threshold tunable.

### Pass 3

| # | Severity | Finding | Resolution |
|---|---|---|---|
| M6 | Medium | The `validate_jsonld` step is "warn, not fail" (§6.2). But invalid JSON-LD published to GBP could be rejected by Google. We should at minimum fail validation if the JSON-LD is invalid JSON; structural Schema.org compliance can be a warning. | Split into two checks: `JsonValidity` (fails) and `SchemaOrgConformance` (warns). |
| L2 | Low | Eval harness is implied (referenced for cost/quality of new prompt versions) but not specified. | Defer to Phase 8 testing work; tracking issue created. |

**M6 resolved.** No remaining H or M findings. **Self-review passes.**

---

## 9. Test Strategy

### 9.1 Unit tests

- `LLMGateway.complete` mocked-provider tests covering: success, primary fail+secondary success, both fail+static, budget exceeded, validation failure, cache hit.
- `PromptStore` tests: version retrieval, A/B cohort selection, parameter validation.
- Each validator class has isolated tests with positive and negative cases.

### 9.2 Integration tests

- End-to-end `ContentBriefGenWorkflow` against a stubbed LLMGateway returning canned responses.
- Approval state-machine: every transition has a test asserting allowed/forbidden moves.
- Budget enforcement: simulate 100 calls at incrementing costs; assert soft warn fires once, hard block fires correctly.

### 9.3 Eval harness (lightweight Phase 4 version)

A fixed dataset of 20 audit-run scenarios with "golden" expected brief outputs. Each prompt version, when promoted to control, must score above a threshold on:
- Schema validity
- Plausible-content score
- Reviewer-acceptance prediction (manual scoring during initial calibration)

This is Phase 4's contribution to the eval harness; a full citation-detection-accuracy eval is Phase 8.

### 9.4 Performance tests

- 10 concurrent ContentBriefGenWorkflow runs against mock provider with 30s latency; assert no workflow exceeds 2 minutes (NF2).
- 1,000 budget checks against `usage_counters`; assert p95 < 50ms (NF6).

### 9.5 Acceptance criteria

| # | Criterion | Verification |
|---|---|---|
| AC1 | A completed AuditRun triggers ContentBriefGenWorkflow and produces 4 briefs in `in_review` state. | Integration test |
| AC2 | A reviewer approves a brief; state changes to `approved`. | E2E test |
| AC3 | A reviewer rejects with notes; new asset is generated incorporating notes. | E2E test |
| AC4 | Anthropic provider failure causes OpenAI fallback; output marked accordingly. | Integration test with provider mocks |
| AC5 | Per-business LLM budget at 100% blocks new content brief gen. | Integration test |
| AC6 | A prompt version flagged for experiment cohort serves only the cohort's traffic. | Manual via PostHog |
| AC7 | A `prompts.invalidated` event clears prompt caches within 30 seconds. | Integration test |

---

## 10. Implementation Tasks (sprint-ready)

For 2 backend engineers + 1 frontend across 3 sprints (6 weeks):

### Sprint 1 — Gateway and primitives
- LLMProvider interface + Anthropic and OpenAI concrete implementations. (3d)
- StaticTemplateProvider with all 4 brief templates. (1d)
- LLMGateway core: provider chain, retry logic, error classification. (3d)
- LLMCall persistence + usage_counters incremental update. (1d)
- Budget pre-check + soft warn + hard block. (1d)
- Cache layer (Redis). (1d)
- PII redactor (regex layer + LLM layer). (1d)

### Sprint 2 — Prompt store, briefs, validators
- prompt_versions table + admin CRUD + invalidate-cache endpoint. (2d)
- Prompt registry seed: all 6 starter prompts with output schemas. (2d)
- Validators: Schema, Length, BusinessFactConsistency, NoForbiddenClaims, PlausibleContent, JsonValidity. (3d)
- ContentBrief + ContentAsset persistence. (1d)
- ContentBriefGenWorkflow (Temporal). (2d)

### Sprint 3 — Approval flow and UI
- Approval state machine + API endpoints. (2d)
- Frontend: agency portal "Pending Approvals" queue. (3d)
- Frontend: brief detail view with diff between versions. (2d)
- Frontend: approve/reject flow with notes capture. (1d)
- Notification triggers (reviewer assigned, brief ready, regen complete). (1d)
- Eval harness skeleton (20 fixtures, automated scoring run). (2d)
- Acceptance criteria walkthrough. (1d)

**Phase 4 exit criteria:**
- §9.5 ACs pass.
- A real audit run on the demo business produces 4 reviewable briefs.
- Cost-tracking dashboard shows per-business LLM spend with budget bars.
- One prompt version has been promoted from experiment to control during this phase (proves the workflow).

---

## 11. Handoff to Phase 5

Phase 5 (Publishing & Entity Seeding) consumes:
- `ContentBrief` in state `approved`, with `current_asset_id` pointing to the final `ContentAsset`.
- The `markdown`, `html`, and `schema_jsonld` fields on the asset are the deliverable Phase 5 publishes.
- The `LLMGateway` and `PromptStore` are also used by Phase 5 for any auxiliary content (e.g., short rewrites for different platforms).

The contract is the `ContentBrief.current_state = 'approved'` flag and the asset's content fields. Phase 4 guarantees that any brief in `approved` has passed all validators and has reviewer sign-off.

---

*CitedBy Phase 4 Design v1.0 | Confidential | May 2026*
*Next: Phase 5 — Publishing & Entity Seeding*
