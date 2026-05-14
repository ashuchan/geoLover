# CitedBy — GEO Platform

**CitedBy** is a Generative Engine Optimization (GEO) SaaS that helps Indian SMBs and digital marketing agencies measure, improve, and maintain their citation presence in AI-generated content (ChatGPT, Perplexity, Google AI Overviews, etc.).

The platform audits how often a business appears in AI responses, generates SEO/GEO-optimized content, publishes it across relevant channels, and tracks citation improvements over time — closing the loop from audit to citation.

---

## Architecture Overview

| Layer | Technology |
|---|---|
| API | FastAPI (Python 3.11), Pydantic v2 |
| ORM | SQLAlchemy 2.0 async |
| Database | PostgreSQL 16 with Row-Level Security (multi-tenant) |
| Cache | Redis 7 |
| Auth | JWT / Auth0 |
| LLM | Anthropic Claude (primary), OpenAI (fallback), static templates (final fallback) |
| Workflows | Temporal (stubs; requires Temporal Cloud for real execution) |
| Migrations | Alembic (8 phases, 001–008) |

### Modules

```
backend/app/modules/
├── identity/        # Phase 1 — Tenants, users, businesses, memberships
├── audit/           # Phase 2 — AI engine crawl, citation detection, scoring
├── reporting/       # Phase 3 — Score snapshots, reports, share links
├── content/         # Phase 4 — LLM gateway, content briefs, validators, PII redaction
├── publishing/      # Phase 5 — Publish targets, OAuth tokens, entity seeding
├── notifications/   # Phase 6 — Recrawl schedules, citation deltas, notification delivery
├── whitelabel/      # Phase 7 — Custom domains, themes, agency portal, bulk import
└── ops/             # Phase 8 — Quota enforcement, impersonation logging, status page
```

### API Routes

| Prefix | Description |
|---|---|
| `POST /api/v1/free-audit` | Public free-audit funnel |
| `/api/v1/tenants` | Tenant management |
| `/api/v1/businesses` | Business profile CRUD |
| `/api/v1/audits` | Audit runs and results |
| `/api/v1/reports` | Score reports and share links |
| `/api/v1/content/briefs` | Content brief lifecycle |
| `/api/v1/publishing/targets` | Publish target management |
| `/api/v1/notifications` | Notification preferences and delivery |
| `/api/v1/recrawl/schedules` | Weekly recrawl scheduling |
| `/api/v1/agency` | Whitelabel config, domains, bulk import |
| `/api/v1/ops` | Quota enforcement, impersonation, status page |

---

## Prerequisites

- Python 3.11+
- Docker & Docker Compose (for PostgreSQL + Redis)
- `pip` / `venv`

---

## Local Setup

### 1. Clone and enter the backend directory

```bash
git clone https://github.com/ashuchan/geoLover.git
cd geoLover/backend
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### 3. Start PostgreSQL and Redis

```bash
docker compose up -d
```

This starts:
- PostgreSQL 16 on `localhost:5432` (db: `citedby`, user: `citedby_app`, password: `localpassword`)
- Redis 7 on `localhost:6379`

### 4. Run database migrations

```bash
alembic upgrade head
```

This applies all 8 migration phases (001–008), creating the full schema with RLS policies, indexes, and enum types.

### 5. Configure environment variables

Create a `.env` file in `backend/`:

```env
DATABASE_URL=postgresql+asyncpg://citedby_app:localpassword@localhost/citedby
REDIS_URL=redis://localhost:6379
SECRET_KEY=your-secret-key-min-32-chars
AUTH0_DOMAIN=your-tenant.auth0.com
AUTH0_AUDIENCE=https://api.citedby.app
ANTHROPIC_API_KEY=sk-ant-...        # optional; fallback to static templates if absent
OPENAI_API_KEY=sk-...               # optional; fallback to static templates if absent
```

### 6. Start the API server

```bash
uvicorn app.main:app --reload --port 8000
```

API is now available at `http://localhost:8000`.
Interactive docs: `http://localhost:8000/docs`

---

## Running Tests

### Unit tests (no Docker required)

```bash
pytest tests/unit/
```

Runs **1,276 tests** using mocked sessions (SQLite in-memory via `aiosqlite`). Coverage target: ≥80% (currently 97%).

```bash
# With coverage report
pytest tests/unit/ --cov=app --cov-report=term-missing
```

### Integration tests (Docker required)

Integration tests use a real PostgreSQL 16 container via [testcontainers](https://testcontainers.com/). They skip automatically when Docker is unavailable.

```bash
pytest tests/integration/ -m integration -v
```

Covers **59 scenarios** across all 8 phases:
- Tenant/user/business CRUD through real repositories
- ContentBrief state machine (draft → in_review → approved)
- PublishAttempt idempotency key uniqueness
- Notification preference upsert and deduplication
- WhitelabelConfig get-or-create and color validation
- Quota enforcement (ok / soft_warn / hard_block / grace)
- Report and ShareLink lifecycle

### Full suite

```bash
pytest
```

> Integration tests will be skipped if Docker is not running.

### Run a specific module's tests

```bash
pytest tests/unit/ -k "content"      # content module tests
pytest tests/unit/ -k "publishing"   # publishing module tests
pytest tests/unit/ -k "router"       # all router tests
```

---

## Database Migrations

```bash
# Apply all migrations
alembic upgrade head

# Roll back one step
alembic downgrade -1

# Show current revision
alembic current

# Show migration history
alembic history --verbose
```

Migration files are in `backend/migrations/versions/`:

| File | Phase | Description |
|---|---|---|
| `001_phase1_initial.py` | 1 | Core schema: tenants, users, businesses |
| `002_phase2_audit.py` | 2 | Audit runs, queries, engine responses |
| `003_phase3_reporting.py` | 3 | Score snapshots, reports, share links |
| `004_phase4_content.py` | 4 | Prompt versions, content briefs, LLM calls |
| `005_phase5_publishing.py` | 5 | Publish targets, OAuth tokens, entity seeds |
| `006_phase6_notifications.py` | 6 | Recrawl schedules, citation deltas, notifications |
| `007_phase7_whitelabel.py` | 7 | Domain mappings, whitelabel configs, theme assets |
| `008_phase8_ops.py` | 8 | Quota logs, grace extensions, impersonation log |

---

## Project Structure

```
geoLover/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── router.py          # Mounts all routers
│   │   │       └── routers/           # One file per module
│   │   ├── core/
│   │   │   ├── config.py              # Settings (pydantic-settings)
│   │   │   ├── database.py            # AsyncSession factory + RLS injection
│   │   │   ├── exceptions.py          # Typed exception hierarchy
│   │   │   └── events.py              # In-process EventBus
│   │   ├── modules/                   # Domain modules (see above)
│   │   └── main.py                    # FastAPI app factory
│   ├── migrations/
│   │   └── versions/                  # Alembic migration files
│   ├── tests/
│   │   ├── conftest.py                # Shared fixtures (sqlite_session, pg_session)
│   │   ├── unit/                      # 1,276 unit tests
│   │   └── integration/               # 59 integration tests
│   ├── docker-compose.yml
│   ├── alembic.ini
│   └── pyproject.toml
└── docs/
    ├── CitedBy_HLD_v1.md              # High-level design
    ├── CitedBy_Phase*_Design.md       # Per-phase design documents
    └── CitedBy_Roadmap.md             # Implementation index
```

---

## Key Design Decisions

- **Multi-tenancy via PostgreSQL RLS** — every table has `tenant_id`; RLS policies enforce isolation at the database level. Tenant context is injected as a session variable (`app.current_tenant`) at the start of each request.
- **Envelope encryption for secrets** — OAuth tokens and DKIM private keys are encrypted with a per-record DEK, which is itself wrapped by a KMS master key. Plain tokens never touch persistent storage.
- **LLM fallback chain** — all LLM calls go through `LLMGateway`: Anthropic → OpenAI → static template. Budget limits are enforced before each call.
- **Idempotency everywhere** — `PublishAttempt`, `Notification`, and `EntitySeed` all use deterministic idempotency keys so retries never produce duplicates.
- **Temporal for durable workflows** — all long-running operations (audits, publishing, recrawl, token refresh) are modeled as Temporal workflows. Phase 1–8 ship stubs that raise `NotImplementedError`; connecting Temporal Cloud is a configuration step, not a code change.

---

## License

Proprietary — CitedBy, 2026.
