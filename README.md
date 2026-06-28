# ⚡ JobPlatform AI

> **AI-Powered Autonomous Job Discovery & Application Platform**
>
> Discovers jobs across 10+ platforms, scores them against your profile, auto-applies when ≥80% match, generates tailored resumes & cover letters, and preps you for interviews — all on autopilot.

---

## Architecture

```
Frontend (Next.js 14)  →  Python FastAPI  →  Celery Workers
       ↓                        ↓                  ↓
  Supabase Auth          Claude AI (Anthropic)   Playwright
  Supabase DB            Match Scoring           Job Scrapers
  Supabase Storage       Cover Letter Gen        Auto-Apply Bot
                         Interview Prep          Email (Resend)
                              ↓
                         Redis (Upstash/Local)
```

---

## Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Node.js | ≥ 20 | https://nodejs.org |
| Python | ≥ 3.11 | https://python.org |
| Docker + Docker Compose | latest | https://docker.com |
| Git | any | https://git-scm.com |

---

## Quick Start (Docker — Recommended)

This starts everything: Redis, FastAPI, Celery worker, Celery Beat scheduler, and Next.js.

### 1 — Clone & configure

```bash
git clone <your-repo-url> job-platform
cd job-platform

cp .env.example .env
# Open .env and fill in the values (see "Environment Variables" below)
nano .env
```

### 2 — Set up Supabase

1. Go to https://supabase.com → New project
2. Once created, open **SQL Editor** and run these files in order:
   ```
   database/schema.sql      ← tables, indexes, triggers, views
   database/rls_policies.sql ← row-level security
   ```
3. Enable **Google OAuth** under Authentication → Providers → Google
4. Set redirect URL: `http://localhost:3000/auth/callback`
5. Copy these values into your `.env`:
   - `SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_URL`
   - `SUPABASE_ANON_KEY` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`
   - `SUPABASE_SERVICE_ROLE_KEY` (Settings → API → service_role key)
   - `SUPABASE_JWT_SECRET` (Settings → API → JWT Secret)

### 3 — Get API keys

#### Anthropic (Claude AI) — Required
1. https://console.anthropic.com → API Keys → Create Key
2. Add to `.env` as `ANTHROPIC_API_KEY=sk-ant-...`

#### OpenAI (Embeddings) — Required
1. https://platform.openai.com → API Keys → Create
2. Add to `.env` as `OPENAI_API_KEY=sk-...`
   > Used only for `text-embedding-3-small` to power semantic job matching.
   > Cost: ~$0.002 per 1M tokens — essentially free.

#### Resend (Email) — Required
1. https://resend.com → Create account (free: 3,000 emails/month)
2. API Keys → Create API Key
3. Add as `RESEND_API_KEY=re_...`
4. Verify your sending domain or use `onboarding@resend.dev` for testing

### 4 — Build & start

```bash
docker compose up --build
```

Services that start:
| Service | URL | Purpose |
|---------|-----|---------|
| `web` | http://localhost:3000 | Next.js frontend |
| `api` | http://localhost:8000 | FastAPI backend |
| `api` docs | http://localhost:8000/docs | Swagger UI |
| `redis` | localhost:6379 | Task queue |
| `worker` | — | Celery job worker |
| `beat` | — | Celery scheduler |

> **First build takes ~5 min** — it installs Playwright's Chromium browser.

### 5 — Open the app

Go to **http://localhost:3000** → Sign in with Google or magic link email.

---

## Manual Setup (without Docker)

If you prefer to run services individually:

### Terminal 1 — Redis

```bash
# macOS
brew install redis && redis-server

# Ubuntu
sudo apt install redis-server && sudo service redis-server start

# Or use Upstash (free, no install): https://upstash.com
# Set REDIS_URL=rediss://... in .env
```

### Terminal 2 — Python API

```bash
cd apps/api

python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Start FastAPI
uvicorn main:app --reload --port 8000
```

### Terminal 3 — Celery Worker

```bash
cd apps/api
source venv/bin/activate

celery -A workers.celery_app worker \
  --loglevel=info \
  -Q discovery,automation,notifications \
  -c 2
```

### Terminal 4 — Celery Beat (Scheduler)

```bash
cd apps/api
source venv/bin/activate

celery -A workers.celery_app beat --loglevel=info
```

### Terminal 5 — Next.js Frontend

```bash
cd apps/web

npm install
npm run dev
```

Open **http://localhost:3000**

---

## Environment Variables Reference

Copy `.env.example` to `.env` and fill in every value.

```bash
# ── Supabase (required) ──────────────────────────────────────
NEXT_PUBLIC_SUPABASE_URL=https://abcdefgh.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGci...          # public key, safe for browser
SUPABASE_URL=https://abcdefgh.supabase.co
SUPABASE_ANON_KEY=eyJhbGci...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...              # KEEP SECRET — server-only
SUPABASE_JWT_SECRET=your-jwt-secret                # Settings → API → JWT Secret

# ── AI (required) ────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-proj-...

# ── Email (required) ─────────────────────────────────────────
RESEND_API_KEY=re_123abc...

# ── Redis (required) ─────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1

# ── App ──────────────────────────────────────────────────────
NEXT_PUBLIC_API_URL=http://localhost:8000           # Frontend → API
ALLOWED_ORIGINS=http://localhost:3000              # CORS whitelist
DEBUG=true
```

---

## First Steps After Login

### Step 1 — Complete your profile
Go to **Settings** → fill in:
- Name, headline, location, years of experience
- Skills (comma-separated — this drives job matching)
- Expected salary range
- Career goals (1-2 sentences — used in cover letter generation)

### Step 2 — Upload your resume
Go to **Resume** → drag and drop your PDF or DOCX.
The AI will automatically:
- Parse and extract skills, experience, education
- Sync extracted skills to your profile
- Generate an ATS compatibility score

### Step 3 — Add job board credentials (for auto-apply)
Go to **Settings → Job Board Credentials** → add your LinkedIn and Naukri username/password.
These are needed for the application bot to submit applications on your behalf.

### Step 4 — Configure automation
Go to **Settings → Automation**:
- Toggle **Enable Auto-Apply** ON
- Set your **threshold** (default 80%) — jobs scoring at or above this auto-apply
- Select your **preferred platforms**

### Step 5 — Trigger first discovery
Go to **Dashboard** → click **"Discover Jobs"**.
The system will:
1. Search LinkedIn, Naukri, and Indeed for roles matching your skills
2. Score each job against your profile using Claude AI
3. Auto-queue applications for 80%+ matches
4. Add 60–79% matches to your "Recommended" list
5. Notify you by email when done

---

## How Each Feature Works

### Job Discovery (every 4 hours automatically)
```
Celery Beat → discover_jobs_for_user task
  → LinkedIn / Naukri / Indeed scrapers (Playwright)
  → Parse each JD with Claude
  → Score against user profile (2-stage: embeddings + Claude)
  → Insert into job_applications table with tier
  → Queue auto_apply tier jobs in apply_queue
  → Email notification of new matches
```

### Auto-Apply Bot (every 30 minutes)
```
Celery Beat → process_apply_queue task
  → Load pending apply_queue items
  → For each: generate tailored cover letter (Claude)
  → Open Playwright browser
  → LinkedIn: Easy Apply flow automation
  → Naukri: Login + click apply
  → Other: Generic form detection + fill
  → Capture confirmation ID + screenshot
  → Email notification to user
```

### Match Scoring
```
User profile (skills, experience, goals)
  + Job description (parsed by Claude)
  ↓
Stage 1: sentence-transformers embedding similarity (fast filter)
Stage 2: Claude deep analysis → 0-100 score + breakdown
  ↓
tier assignment: auto_apply / recommended / watchlist / archived
```

### Interview Prep (on demand)
```
Click "Prep" on any application
  → Claude generates:
     - 5 technical questions with ideal answers
     - 5 behavioral (STAR format)
     - 3 system design questions
     - 3 coding challenges
     - Company research + culture notes
     - Questions to ask the interviewer
     - Salary negotiation strategy
     - Day-by-day prep plan
```

---

## Project Structure

```
job-platform/
├── .env.example               ← Copy to .env
├── docker-compose.yml         ← All services
├── database/
│   ├── schema.sql             ← Run first in Supabase
│   └── rls_policies.sql       ← Run second in Supabase
│
├── apps/
│   ├── api/                   ── Python FastAPI
│   │   ├── main.py            ← App entry point
│   │   ├── config.py          ← Settings (reads .env)
│   │   ├── database.py        ← Supabase clients
│   │   ├── models/            ← Pydantic models
│   │   ├── routers/           ← API routes
│   │   │   ├── jobs.py        ← GET /jobs, POST /jobs/discover
│   │   │   ├── applications.py← Pipeline, status, interview prep
│   │   │   ├── resumes.py     ← Upload, parse, tailor
│   │   │   ├── ai.py          ← Skill gaps, copilot, cover letter
│   │   │   └── automation.py  ← Credentials, queue, settings
│   │   ├── services/
│   │   │   ├── ai_service.py  ← All Claude API calls
│   │   │   └── notification_service.py ← Resend email
│   │   ├── scrapers/
│   │   │   ├── base.py        ← Playwright browser management
│   │   │   ├── linkedin.py    ← LinkedIn scraper + Easy Apply
│   │   │   ├── naukri.py      ← Naukri scraper
│   │   │   └── indeed.py      ← Indeed scraper
│   │   └── workers/
│   │       ├── celery_app.py  ← Celery config + beat schedule
│   │       ├── job_discovery.py ← Scheduled job search
│   │       ├── application_bot.py ← Auto-apply pipeline
│   │       └── notification_worker.py ← Follow-ups, digests
│   │
│   └── web/                   ── Next.js 14 Frontend
│       ├── src/app/
│       │   ├── page.tsx       ← Landing page
│       │   ├── auth/login/    ← Google OAuth + magic link
│       │   ├── dashboard/     ← Kanban pipeline
│       │   ├── jobs/          ← Job matches grid
│       │   ├── applications/  ← Table + status management
│       │   ├── resume/        ← Upload + AI parsing
│       │   ├── interview/     ← Interview prep hub
│       │   ├── analytics/     ← Charts + funnel metrics
│       │   └── settings/      ← Profile + automation config
│       └── src/
│           ├── components/    ← All UI components
│           ├── lib/           ← Supabase clients, API client, utils
│           └── types/         ← TypeScript interfaces
```

---

## API Reference

Full interactive docs at **http://localhost:8000/docs** (Swagger UI).

Key endpoints:

```
GET    /api/v1/jobs/                 List matched jobs
POST   /api/v1/jobs/discover         Trigger discovery
POST   /api/v1/jobs/{id}/score       Score a specific job

GET    /api/v1/applications/pipeline Get Kanban pipeline
GET    /api/v1/applications/         List all applications
PATCH  /api/v1/applications/{id}     Update status/notes
POST   /api/v1/applications/{id}/apply   One-click apply
GET    /api/v1/applications/{id}/interview-prep  Get/generate prep

POST   /api/v1/resumes/upload        Upload + AI parse resume
POST   /api/v1/resumes/{id}/tailor   Tailor to specific job

GET    /api/v1/ai/skill-gaps         Analyze your skill gaps
POST   /api/v1/ai/copilot            Ask career questions
POST   /api/v1/ai/cover-letter       Generate cover letter

POST   /api/v1/automation/credentials   Save job board login
PATCH  /api/v1/automation/settings      Toggle auto-apply
```

---

## Deployment (Production)

### Frontend → Vercel

```bash
cd apps/web
npx vercel --prod
# Set all NEXT_PUBLIC_* env vars in Vercel dashboard
```

### Backend → Railway or Render

```bash
# Railway
railway login
railway init
railway up --service api

# Add all env vars in Railway dashboard
# Set start command: uvicorn main:app --host 0.0.0.0 --port $PORT
```

### Redis → Upstash

1. https://upstash.com → New Redis database
2. Copy `REDIS_URL` (starts with `rediss://`) into all services

### Workers → Railway (separate service)

```bash
# Add a second Railway service pointing to same repo
# Set start command: celery -A workers.celery_app worker --loglevel=info
```

### Beat Scheduler → Railway (separate service)

```bash
# Start command: celery -A workers.celery_app beat --loglevel=info
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `supabase connection refused` | Check `SUPABASE_URL` in `.env` — must include `https://` |
| `anthropic.AuthenticationError` | Verify `ANTHROPIC_API_KEY` starts with `sk-ant-` |
| `playwright._impl._api_types.Error: browserType.launch` | Run `playwright install chromium` in `apps/api/` |
| Login redirects loop | Ensure Supabase redirect URL is `http://localhost:3000/auth/callback` |
| Jobs not discovering | Check Celery worker is running; check Redis connection |
| Auto-apply not working | Add job board credentials in Settings; enable auto-apply toggle |
| `CORS error` in browser | Add your frontend URL to `ALLOWED_ORIGINS` in `.env` |
| Schema errors | Re-run `database/schema.sql` in Supabase SQL Editor |

---

## Cost Estimate (Monthly)

| Service | Free Tier | Paid |
|---------|-----------|------|
| Supabase | 500MB DB, 2GB storage | $25/mo Pro |
| Anthropic (Claude) | Pay per use | ~$5–20/mo typical |
| OpenAI (Embeddings) | Pay per use | ~$0.50/mo |
| Resend (Email) | 3,000 emails/mo | $20/mo for 50k |
| Upstash Redis | 10k req/day free | $10/mo |
| Vercel (Frontend) | Hobby free | $20/mo Pro |
| Railway (Backend) | $5 credit/mo | ~$10/mo |

**Total: ~$0–$20/mo for solo use on free tiers**

---

## Known Limitations

1. **LinkedIn rate limiting** — LinkedIn actively detects bots. The scraper uses stealth techniques but may get temporarily blocked. Use reasonable discovery intervals (4+ hours).

2. **CAPTCHA** — Some portals serve CAPTCHAs. The bot currently cannot solve them; those applications fall back to the queue for manual retry.

3. **OTP-based logins** — Platforms that require OTP via phone on every login (e.g. some Naukri flows) cannot be fully automated without storing OTP delivery access.

4. **PDF parsing accuracy** — Complex resume layouts (multi-column, heavy graphics) may parse with lower accuracy. Plain text or ATS-friendly formats work best.

5. **pgvector requirement** — Supabase's free plan supports pgvector. Self-hosted Postgres requires `CREATE EXTENSION vector;` manually.

---

## License

MIT — use freely, build on top, contribute back.
