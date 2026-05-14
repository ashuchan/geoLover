# CitedBy — Implementation Roadmap
**Version:** 1.0
**Date:** May 2026
**Author:** CTO, CitedBy
**Status:** Definitive index for the design package

---

## 1. Purpose

This document is the **single starting point** for anyone working with the CitedBy design package. It indexes the ten approved-for-implementation documents, shows their dependencies, maps each phase's outputs to product capabilities, lays out the recommended implementation timeline, and identifies the critical-path decisions that drive everything else.

This is not a design document. It contains no new design decisions. Everything substantive lives in the documents it references. Its job is wayfinding.

---

## 2. Document Index

The design package consists of one architectural reference and nine phase designs:

| # | Document | Status | Length | Self-review |
|---|---|---|---|---|
| 1 | `CitedBy_HLD_v1.md` | Approved | ~580 lines | Clean (3 passes) |
| 2 | `CitedBy_Phase0_Design.md` — Infrastructure & Foundation | Approved | ~560 lines | Clean (3 passes) |
| 3 | `CitedBy_Phase1_Design.md` — Identity, Tenancy & Business Profile | Approved | ~940 lines | Clean (3 passes) |
| 4 | `CitedBy_Phase2_Design.md` — Audit & Citation Detection | Approved | ~940 lines | Clean (3 passes) |
| 5 | `CitedBy_Phase3_Design.md` — Reporting & Free Audit Experience | Approved | ~680 lines | Clean (3 passes) |
| 6 | `CitedBy_Phase4_Design.md` — Content Generation & LLM Gateway | Approved | ~750 lines | Clean (3 passes) |
| 7 | `CitedBy_Phase5_Design.md` — Publishing & Entity Seeding | Approved | ~775 lines | Clean (3 passes) |
| 8 | `CitedBy_Phase6_Design.md` — Weekly Recrawl & Notifications | Approved | ~690 lines | Clean (3 passes) |
| 9 | `CitedBy_Phase7_Design.md` — Whitelabel & Agency Portal | Approved | ~780 lines | Clean (3 passes) |
| 10 | `CitedBy_Phase8_Design.md` — Hardening, Security Review, Launch | Approved | ~700 lines | Clean (3 passes) |

Reading order for a new team member:
1. Read the **HLD** first. It is the canonical architectural reference.
2. Read **Phase 1** to understand the foundational data model.
3. Read the phase you are about to implement.
4. Read adjacent phases for context (the "Handoff" section in each phase tells you what it produces for the next).

---

## 3. Phase Summary at a Glance

| Phase | Name | Primary Modules | Duration | Team |
|---|---|---|---|---|
| 0 | Infrastructure & Foundation | GCP, Postgres, Temporal, Auth0, CI/CD, observability | 3 weeks | 1 platform eng + CTO |
| 1 | Identity, Tenancy & Business Profile | M1: Identity & Tenancy, M2: Business Profile | 4 weeks | 2 BE + 1 FS |
| 2 | Audit & Citation Detection | M3: Audit & Crawl | 5 weeks | 2 BE + 1 ML/NLP |
| 3 | Reporting & Free Audit Experience | M7: Reporting (+ audit UX) | 3 weeks | 1 BE + 2 FE |
| 4 | Content Generation & LLM Gateway | M4: Content Generation | 6 weeks | 2 BE + 1 FE |
| 5 | Publishing & Entity Seeding | M5: Publishing, M6: Entity Seeding | 6 weeks | 2 BE + 1 FE |
| 6 | Weekly Recrawl & Notifications | M8: Notifications + recrawl loop | 5 weeks | 2 BE + 1 FE |
| 7 | Whitelabel & Agency Portal | M10: Whitelabel + agency UX | 6 weeks | 2 BE + 2 FE |
| 8 | Hardening, Security Review, Launch | All — cross-cutting | 4 weeks | 3 + CTO + vendors |
| | | **Total (sequential)** | **42 weeks** | |
| | | **Total (with parallelisation)** | **~30 weeks** | |

The "with parallelisation" total assumes the parallelisation opportunities in §6.

---

## 4. Dependency Graph

```
                            ┌──────────────────────┐
                            │  Phase 0             │
                            │  Infrastructure      │
                            └──────────┬───────────┘
                                       │
                            ┌──────────▼───────────┐
                            │  Phase 1             │
                            │  Identity & Profile  │
                            └────┬──────────┬──────┘
                                 │          │
                ┌────────────────┘          └────────────────┐
                │                                            │
     ┌──────────▼───────────┐                     ┌──────────▼──────────┐
     │  Phase 2             │                     │  (parallel optional)│
     │  Audit & Detection   │                     │   Marketing site,   │
     └────┬──────────┬──────┘                     │   help center prep  │
          │          │                            └─────────────────────┘
          │          │
          │     ┌────▼────────────┐
          │     │  Phase 3        │
          │     │  Reporting +    │
          │     │  Free Audit UX  │
          │     └────┬────────────┘
          │          │
          ▼          ▼
     ┌──────────────────────┐
     │  Phase 4             │
     │  Content Gen + LLM   │
     │  Gateway             │
     └──────────┬───────────┘
                │
     ┌──────────▼───────────┐
     │  Phase 5             │
     │  Publishing + Seeds  │
     └──────────┬───────────┘
                │
     ┌──────────▼───────────┐
     │  Phase 6             │
     │  Recrawl + Notify    │
     └──────────┬───────────┘
                │
     ┌──────────▼───────────┐
     │  Phase 7             │
     │  Whitelabel + Agency │
     └──────────┬───────────┘
                │
     ┌──────────▼───────────┐
     │  Phase 8             │
     │  Hardening + Launch  │
     └──────────────────────┘
```

Key dependency facts:
- **Phase 0 unblocks Phase 1.** Nothing else can start until the database, Temporal, and CI exist.
- **Phase 1 unblocks all others.** The tenancy spine is universal.
- **Phase 2 must precede Phase 3** (Reporting consumes AuditRuns).
- **Phase 4 needs Phase 2** for the audit-quick-wins LLM use, and Phase 3 for the report wiring.
- **Phase 5 needs Phase 4** (content to publish).
- **Phase 6 needs Phase 5** (publishes to recrawl-attribute-back-to).
- **Phase 7 can begin after Phase 1** technically (the multi-tenancy spine is all it strictly needs); practically it waits for Phase 5 so the agency portal has something operational to display.
- **Phase 8 needs everything.**

---

## 5. Phase Outputs → Product Capabilities

What does each phase let a customer (or operator) actually *do*?

| After this phase | The product can... |
|---|---|
| 0 | (Nothing customer-facing — substrate only) |
| 1 | Sign up; create a tenant; create a business profile; submit a free-audit request (no audit runs yet) |
| 2 | Run an audit (real engine probes, real citation detection, real score) |
| 3 | See the audit report in browser + PDF; receive the report by email; explore the free-audit funnel end-to-end |
| 4 | Generate content briefs from audit findings; review and approve them |
| 5 | Connect Google Business Profile / WordPress; publish approved briefs; submit to directories; verify publication |
| 6 | Receive a weekly digest of citation changes; receive alerts for OAuth failures and other actionable events; configure notification preferences |
| 7 | Agencies can fully brand the experience; agencies can bulk-import clients; custom domains work; branded emails go out |
| 8 | All of the above, in production, safely, at MVP scale, with operational support |

**The customer-visible MVP comes online at Phase 3** (free audit) and **the paid product comes online at Phase 5** (closed-loop content + publish). Phase 6 makes it a service. Phases 7–8 make it a business.

---

## 6. Implementation Timeline

### 6.1 Sequential timeline (42 weeks)

```
W:  1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40 41 42
P0: ███
P1:    ██████
P2:           ████████
P3:                   █████
P4:                        ████████████
P5:                                    ████████████
P6:                                                ██████████
P7:                                                          ████████████
P8:                                                                      ████████
                                                                                ↑
                                                                              LAUNCH
```

### 6.2 Parallelised timeline (~30 weeks)

Several phases can run in parallel after their dependencies clear:

- **Phase 3** (reporting) can run partly parallel to Phase 2 (the audit engine) because Phase 3's UX work and Phase 2's algorithmic work do not overlap day-to-day.
- **Phase 4** (content gen) can start before Phase 3 (reporting) is fully complete, because they share only the audit data layer.
- **Phase 7** (whitelabel) backend work can start as early as after Phase 1; only the customer-facing UI integration needs the rest.
- **Phase 8** preparatory work (vendor selection for pen test, runbook authoring) can start during Phase 7.

```
W:  1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30
P0: ███
P1:    ██████
P2:           ████████
P3:               ████████
P4:                   ████████████
P5:                            ████████████
P6:                                       ██████████
P7:                                ██████████████████
P8 prep:                                       █████
P8 launch:                                                                █████
                                                                              ↑
                                                                            LAUNCH
```

The parallelisation requires:
- **Team size of at least 5 engineers** (2 BE focused on backend modules, 1 NLP/ML for Phase 2 algorithms, 2 FE for UI work, plus a platform eng floating).
- **Discipline on the seams.** Modules consuming other modules' interfaces must mock those interfaces during parallel development; the producing module ships a stable contract early.

---

## 7. Critical-Path Decisions

These are decisions that, if delayed or wrong, cascade through multiple phases. They must be made early and held to.

| # | Decision | Made in | Cascades into |
|---|---|---|---|
| CP1 | Postgres + RLS over schema-per-tenant or DB-per-tenant | HLD §6.4 | Phases 1, 7, 8 — would require redesign if revisited |
| CP2 | Temporal Cloud over self-hosted workflow / Celery / BullMQ | HLD §6.3 | Every long-running workflow in Phases 2, 4, 5, 6 |
| CP3 | Modular monolith over microservices | HLD §6.2 | All phases — extraction strategy assumes this baseline |
| CP4 | Adapter pattern for AI engines, publishers, notification channels | HLD §10.7 + Phases 2, 5, 6 | All external integrations |
| CP5 | Prompts and templates as data, not code | HLD §10.7 | Phases 4, 6 — Phase 4's prompt store is a substantive design |
| CP6 | `asia-south1` data residency commitment | HLD §10.5 | Every infrastructure decision |
| CP7 | LLM Gateway as single chokepoint for all model calls | Phase 4 §4 | Phase 2 (audit-quick-wins), Phase 4 (briefs), any future LLM use |
| CP8 | OAuth tokens with KMS envelope encryption | Phase 5 §5 | Any future integrations involving tokens |
| CP9 | Bucket-based recrawl schedules (not per-business) | Phase 6 §4.1 | Operational cost at scale |
| CP10 | Two-tier unsubscribe (marketing vs. critical) | Phase 6 §5.8 | Email design for the lifetime of the product |

If any of these decisions is reversed, the documents downstream of it require revision. None should be reversed lightly.

---

## 8. Team-Size Scenarios

### 8.1 The minimum-viable team

**3 engineers + CTO** can deliver the product, but at the **fully sequential 42-week** pace. CTO acts as platform engineer during Phase 0 and as floating tech lead afterward.

Risks at this size:
- On-call burden is heavy (1-in-3 rotation).
- A single departure becomes critical-path.
- Specialised work (Phase 2 NLP, Phase 7 SSL/DNS) requires CTO or external contractor help.

### 8.2 The recommended team

**5 engineers (2 BE, 1 NLP/ML, 2 FE) + CTO** delivers the parallelised **~30-week** timeline.

Specialisation:
- 1 BE owns Phases 1, 4 (Identity, Content Gen).
- 1 BE owns Phases 5, 6 (Publishing, Notifications).
- 1 NLP/ML owns Phase 2 (Audit & Citation Detection — the highest algorithmic complexity).
- 1 FE owns Phases 3, 7 (Reporting UI, Whitelabel UI).
- 1 FE owns the agency dashboard and operational UI.
- CTO floats; owns architectural reviews, security, vendor management; runs Phase 8.

### 8.3 The scale-up team

**8 engineers** is roughly when extraction-to-services starts paying for itself (HLD §13.2: the 10k-customer threshold). At MVP scale (200 audits, 25 paying customers, 5 agencies) 8 engineers is overcapacity — adding people will not shorten the critical path; coordination cost rises.

We recommend 5 engineers through launch; hire to 7–8 in the 6 months after launch as the product proves out.

---

## 9. Cumulative Self-Review Summary

Across the ten design documents, the self-review process surfaced:

| Severity | Findings raised | Findings resolved |
|---|---|---|
| High | 22 | 22 |
| Medium | 47 | 47 |
| Low | 18 | 18 (some accepted as documented limitations) |
| **Total** | **87** | **87** |

The high-severity findings clustered around five themes:
1. **Multi-tenancy edge cases** — public surfaces, scope changes, agency takeover (Phases 1, 5, 7).
2. **Idempotency under retry** — workflows, publishes, notifications (Phases 4, 5, 6).
3. **External dependency fragility** — engine adapters, OAuth tokens, DNS (Phases 2, 5, 7).
4. **Cost runaway** — LLM budgets, schedule scale (Phases 4, 6).
5. **Operational safety** — pen test re-validation, DR drill, billing enablement (Phase 8).

The fact that no high finding survived three review passes is the bar we held ourselves to. The fact that every phase generated such findings suggests the bar was the right height — we caught things that would have hurt us in production.

---

## 10. What Is Explicitly NOT in This Design

The package designs CitedBy MVP. The following are deliberately deferred to post-launch (Phase 2 in PRD parlance) with the architectural seams in place:

| Deferred capability | Where the seam exists |
|---|---|
| Vernacular (Hindi, Kannada, Tamil) content generation | Phase 4 `PromptVersion.locale` field; channel adapters accept locale |
| Sarvam, Krutrim engine adapters | Phase 2 `AIEngineAdapter` interface |
| Justdial, IndiaMart, Sulekha publisher adapters | Phase 5 `PublisherAdapter` interface; directory registry has rows |
| WhatsApp customer notifications | Phase 6 channel built; awaits WABA approval |
| SMS, push notifications | None — would be a new channel adapter when justified |
| Public developer API / OAuth-for-third-parties | Phase 8 explicitly excludes |
| Multi-region deployment | HLD §13.2 — post-Series B |
| Real-time citation alerting (sub-weekly) | Phase 6 cadence config; would extend `notification_cadence` enum |
| Mobile app | Out of scope; web-first |
| SOC 2 audit | Phase 8 begins the process; report comes post-launch |

The architecture supports each of these. None requires a redesign to add.

---

## 11. The Commitment

This design package represents ~85,000 words across ten documents, every section subjected to three-pass self-review with explicit H/M findings and explicit resolutions. The work was structured to make implementation predictable, decisions auditable, and trade-offs visible.

The commitment from the CTO to the team and the founders:

1. **The package is the contract.** No phase begins without its design document being approved. Deviations are surfaced as ADRs, not as drift.
2. **The seams are real.** Module boundaries and adapter interfaces are not aspirational — CI guards enforce them. We pay the small cost of discipline now to retain optionality forever.
3. **The self-review bar is preserved.** Every implementation PR is reviewed against its phase design. High and medium concerns surfaced during implementation flow back into the design document and trigger re-review.
4. **Honesty over optimism.** Where uncertainty remains (LLM cost stability, scraping legality, WhatsApp approval timeline), the documents say so. We will not pretend to have certainty we lack.
5. **The product will be excellent.** Not because the design is perfect — no design is — but because every decision was made deliberately, every risk was confronted, and every trade-off was made by humans who understood what they were trading off.

Ready to build.

---

*CitedBy Implementation Roadmap v1.0 | Confidential | May 2026*
*Single starting point for the design package. All substantive content lives in the referenced documents.*
