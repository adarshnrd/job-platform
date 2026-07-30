# ⚡ JobPlatform AI

> **AI-Powered Autonomous Job Discovery & Application Platform**
>
> Discovers jobs across 30+ India and global sources, scores them against your profile with dual-LLM evaluation, auto-applies when ≥80% match (or prepares an assisted application you confirm), generates tailored cover letters, detects and answers application questions, and preps you for interviews.

---

## Architecture

```
Frontend (Next.js 14)  →  Python FastAPI  →  APScheduler (in-process)
       ↓                        ↓                    ↓
  Supabase Auth          Groq + NVIDIA LLMs     Playwright scrapers
  Supabase DB            Match scoring          Session-based auto-apply
  Supabase Storage       Cover letters          Answer Bank
                         Interview prep         Email (Resend, optional)
```

**No Redis, no Celery, no separate worker processes.** Background jobs (discovery,
apply-queue drain, listing revalidation, stuck-app recovery, session health,
notifications) run in-process via APScheduler, started/stopped by the FastAPI
lifespan. This keeps the whole backend a single `uvicorn` process — ideal for
local, single-user operation.

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Node.js | ≥ 20 | https://nodejs.org |
| Python | ≥ 3.11 | https://python.org |
| Git | any | https://git-scm.com |

A hosted **Supabase** project provides Postgres, auth, and storage — there is no
local database to run.

---

## Quick Start

### 1 — Clone & configure

```bash
git clone <your-repo-url> job-platform
cd job-platform
cp .env.example .env     # then fill in the values (see "Environment Variables")
```

### 2 — Set up Supabase

1. Go to https://supabase.com → New project.
2. Open **SQL Editor** and run these files **in order**:
   ```
   database/schema.sql               ← tables, indexes, triggers, views
   database/rls_policies.sql         ← row-level security
   database/02_api_sources.sql       ← extra source_platform enum values
   database/03_application_tracking.sql
   database/04_session_auth.sql      ← encrypted session storage
   database/05_rate_limiting.sql
   database/05_recency_relevance.sql ← posted_at + recency view columns
   database/06_listing_validation.sql← stale-listing expiry + view columns
   database/07_discovery_prefs.sql   ← per-user discovery toggle
   database/15_global_sources.sql    ← global sources + users.discovery_region
   ```
   > Migrations 08–14 are listed in `database/` and follow the same ordering.
   > Run `15_global_sources.sql` on its own — it uses `ALTER TYPE ... ADD VALUE`,
   > which cannot share a transaction with statements that use the new values.
3. Enable **Google OAuth** under Authentication → Providers → Google.
4. Set redirect URL: `http://localhost:3000/auth/callback`.
5. Copy these into `.env`:
   - `SUPABASE_URL` / `NEXT_PUBLIC_SUPABASE_URL`
   - `SUPABASE_ANON_KEY` / `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY` (Settings → API → service_role key — **keep secret**)
   - `SUPABASE_JWT_SECRET` (Settings → API → JWT Secret — enables fast local auth)

### 3 — Get AI keys (at least one required)

The platform routes across providers with automatic failover. You need **at
least one** of:

- **Groq** (free, recommended) — https://console.groq.com → API Keys → `GROQ_API_KEY`
- **NVIDIA NIM** (free credits) — https://build.nvidia.com → `NVIDIA_API_KEY`
- **Anthropic** (optional, for high-quality reasoning tasks) — `ANTHROPIC_API_KEY`

Optional job-source API keys (sources auto-skip when unset): `ADZUNA_APP_ID` +
`ADZUNA_APP_KEY`, `JOOBLE_API_KEY`, `JSEARCH_RAPIDAPI_KEY` (JSearch also powers
Google-for-Jobs results). Optional email: `RESEND_API_KEY`.

### 4 — Generate a session encryption key

Job-board sessions are stored Fernet-encrypted. Generate a key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# put the output in .env as SESSION_ENCRYPTION_KEY=...
```

(For local dev you can leave the default and run with `DEBUG=true`, but you'll get a warning.)

### 5 — Install & run

```bash
# Backend
cd apps/api
python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
uvicorn main:app --reload --port 8000

# Frontend (second terminal)
cd apps/web
npm install
npm run dev
```

Or start both at once from the repo root:

```bash
./scripts/start.sh        # or: make start
```

Open **http://localhost:3000**. Backend health: **http://localhost:8000/health**
(reports DB connectivity + scheduler status). API docs: **http://localhost:8000/docs**.

---

## Environment Variables Reference

```bash
# ── Supabase (required) ──────────────────────────────────────
NEXT_PUBLIC_SUPABASE_URL=https://abcdefgh.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGci...          # public, safe for browser
SUPABASE_URL=https://abcdefgh.supabase.co
SUPABASE_ANON_KEY=eyJhbGci...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...              # KEEP SECRET — server-only
SUPABASE_JWT_SECRET=your-jwt-secret                # Settings → API → JWT Secret

# ── AI (at least one required) ───────────────────────────────
GROQ_API_KEY=gsk_...
NVIDIA_API_KEY=nvapi-...
ANTHROPIC_API_KEY=sk-ant-...                       # optional

# ── Session encryption (required in production) ──────────────
SESSION_ENCRYPTION_KEY=<Fernet key>

# ── Optional job-source API keys (sources auto-skip if unset) ─
ADZUNA_APP_ID=...
ADZUNA_APP_KEY=...
JOOBLE_API_KEY=...
JSEARCH_RAPIDAPI_KEY=...

# ── Optional email (disabled if unset) ───────────────────────
RESEND_API_KEY=re_...

# ── App ──────────────────────────────────────────────────────
NEXT_PUBLIC_API_URL=http://localhost:8000
ALLOWED_ORIGINS=http://localhost:3000
DEBUG=true
```

---

## First Steps After Login

1. **Complete your profile** (Settings) — name, headline, location, years of
   experience, skills (drives matching), expected salary, career goals, plus the
   reusable application-profile fields (work authorization, notice period).
2. **Upload your resume** (Resume) — parsed for skills/experience, synced to your
   profile, scored for ATS compatibility.
3. **Connect job boards** (Settings → Connections) — for auto-apply, connect
   LinkedIn / Naukri via the session handshake (you log in once in a real browser;
   the encrypted session cookies are stored — no passwords are kept).
4. **Configure automation** (Settings → Automation) — toggle auto-apply, set the
   threshold (default 80%), choose preferred platforms, and optionally turn off
   background discovery.
5. **Discover jobs** (Dashboard → Discover) — searches your sources, scores each
   role, auto-queues 80%+ matches, and lists 60–79% as recommended.

---

## How Each Feature Works

### Job Discovery (every 4 hours, or on demand)
```
APScheduler → discovery for each opted-in user
  → region: users.discovery_region if set, else inferred from preferred_locations
  → region-aware source registry (32 sources; keyed API sources auto-skip)
  → batch-parse JDs across Groq + NVIDIA
  → upsert job_listings (dedup on source_url)
  → dual-LLM scoring, double-eval above 70
  → tier: auto_apply (≥80) / recommended (≥60) / watchlist (≥50)
  → queue auto_apply-tier jobs when the user has auto-apply enabled
```

### Auto-Apply (apply queue drained every 30 minutes)
```
APScheduler → drain apply_queue with per-platform daily caps + human delays
  → listing liveness preflight (skip dead jobs)
  → generate tailored cover letter
  → SessionService decrypts the platform session cookies
  → platform adapter (LinkedIn / Naukri) submits; detects form questions
  → unknown questions pause the application (needs_input) instead of guessing
  → record result, audit trail, notify
```

### Reliability jobs (also on APScheduler)
- **Listing revalidation** (every 12h) — marks dead/expired listings inactive.
- **Stuck-application recovery** (every 20 min) — resets applications orphaned
  mid-apply by a crash back to `matched`.
- **Session health checks** (every 6h), **follow-up reminders** (daily 9 AM),
  **weekly digest** (Mon 8 AM).

### Match Scoring
```
User profile + parsed JD → dual-LLM (Groq + NVIDIA) scoring
  → scores above 70 are double-evaluated and reconciled
  → 0–100 score + strengths/gaps/recommendations + tier
```

---

## Project Structure

```
job-platform/
├── database/                  ← SQL schema + ordered migrations
├── docs/
│   ├── API_CONVENTIONS.md
│   └── PORTAL_INTEGRATION_ROADMAP.md   ← 20-portal plan + Answer Bank design
├── scripts/start.sh           ← start backend + frontend together
├── apps/
│   ├── api/                   ── Python FastAPI
│   │   ├── main.py            ← app entry + startup config validation
│   │   ├── scheduler.py       ← APScheduler jobs (replaces Celery/Redis)
│   │   ├── config.py, database.py, auth.py
│   │   ├── models/  routers/  ← Pydantic models, API routes
│   │   ├── services/
│   │   │   ├── ai/            ← provider routing, scoring, content, interview
│   │   │   ├── sessions/      ← encrypted session auth + platform adapters
│   │   │   ├── portals.py     ← portal capability registry (tiers)
│   │   │   ├── listing_validator.py, ranking.py, job_tracker.py, …
│   │   ├── scrapers/          ← 19 job sources (Playwright + API-first)
│   │   └── workers/           ← discovery, application_bot, listing_validator, …
│   └── web/                   ── Next.js 14 frontend
│       └── src/{app,components,lib,types}
```

---

## API Reference

Full interactive docs at **http://localhost:8000/docs**. Selected endpoints:

```
GET    /api/v1/jobs/                      List matched jobs (recency-ranked)
POST   /api/v1/jobs/discover              Trigger discovery
POST   /api/v1/jobs/{id}/report-expired   Mark a dead listing inactive
GET    /api/v1/portals                    Portal capability matrix (tiers)

GET    /api/v1/applications/pipeline      Kanban pipeline
POST   /api/v1/applications/{id}/apply    Queue an application
POST   /api/v1/applications/{id}/prepare  Assisted-apply package

GET    /api/v1/sessions                   Connected job-board sessions
POST   /api/v1/sessions/{platform}/connect  Start login handshake

POST   /api/v1/resumes/upload             Upload + AI-parse resume
GET    /api/v1/export/job-tracker         Download the Excel tracker
```

---

## Deployment Notes

The backend is a single `uvicorn` process (APScheduler runs inside it), so it
deploys like any FastAPI app (Railway/Render/Fly). Point the frontend (Vercel)
at the API via `NEXT_PUBLIC_API_URL`, set every env var, and ensure Playwright's
Chromium is installed in the backend image (`playwright install chromium`). No
Redis or separate worker/beat services are required.

> Note: APScheduler is in-process, so run a **single** backend replica. Running
> multiple replicas would schedule duplicate jobs — a distributed scheduler
> would be needed for horizontal scaling.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Startup aborts with "configuration error(s)" | Fill the missing `.env` values it lists (Supabase keys, at least one AI key) |
| `No AI providers configured` | Set `GROQ_API_KEY` or `NVIDIA_API_KEY` |
| `SESSION_ENCRYPTION_KEY must be changed` | Generate a Fernet key (Quick Start step 4), or set `DEBUG=true` for local dev |
| `playwright ... browserType.launch` | Run `playwright install chromium` in `apps/api/` |
| Login redirects loop | Supabase redirect URL must be `http://localhost:3000/auth/callback` |
| Jobs not discovering | Check `/health` shows scheduler `running`; confirm auto-discovery isn't toggled off |
| Auto-apply not working | Connect the job board in Settings → Connections; enable auto-apply |
| Missing-column / migration errors | Run the pending `database/*.sql` migrations in order |
| `CORS error` | Add your frontend URL to `ALLOWED_ORIGINS` |

---

## Known Limitations

1. **LinkedIn rate limiting** — actively detects automation; conservative daily
   caps and randomized delays are enforced. Keep discovery intervals ≥ 4h.
2. **CAPTCHA / hCaptcha** — never solved programmatically; those portals fall
   back to assisted mode (you confirm in-app).
3. **Single backend replica** — APScheduler is in-process (see Deployment Notes).
4. **PDF parsing** — complex multi-column resumes parse less accurately than
   ATS-friendly layouts.
5. **Boards that block discovery** — a few sources stay registered for display
   and assisted apply but cannot be searched. Each scraper's module docstring
   records what was measured and when.

   | Board | Status |
   |-------|--------|
   | Wellfound | 403 to plain HTTP, headless Chromium, headless *and* headed real Chrome. No scraping path; kept for display + assisted apply. |
   | Peerlist | Listing pages need a **headed** browser; detail pages stay walled, so JDs are usually unavailable. Off by default. |
   | FlexJobs | Paywalled. Only the free `/publicjobs` tier is read, and those links often resolve to removed postings (410). Off by default. |
   | Google Jobs | No direct scraping (consent/bot wall, hashed markup, ToS). Sourced via the licensed JSearch API — set `JSEARCH_RAPIDAPI_KEY`. |

   Peerlist and FlexJobs need a visible browser window, so they only work on a
   local/desktop deployment with `SCRAPER_ALLOW_HEADED=true`. Both drop any
   listing whose JD never loaded rather than spending LLM budget scoring a
   bare title.

### Targeting jobs outside India

Region selection drives which sources run. By default it is inferred from
`preferred_locations`, which cannot express intent — someone living in
Bengaluru who wants roles abroad still infers as `india`. Set
`users.discovery_region` to `global` (migration 15) to override it; the manual
`POST /api/v1/jobs/discover` still accepts a one-off `region` that wins for
that run. A global run reaches Arc, Welcome to the Jungle, Y Combinator,
Foundit's Singapore/Indonesia/Hong Kong boards, the remote boards, and the
overseas roles on ATS company boards.

---

## License

MIT — use freely, build on top, contribute back.

BACKEND
cd /Users/mindpath/Downloads/x12/job-platform/apps/api && ./venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

FRONTEND
cd /Users/mindpath/Downloads/x12/job-platform/apps/web && npm run dev