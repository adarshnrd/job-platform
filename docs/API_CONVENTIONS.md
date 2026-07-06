# API Conventions

## Base URL

All endpoints are prefixed with `/api/v1`. The backend runs on port 8000 by default.

```
http://localhost:8000/api/v1
```

## Authentication

Every request (except `/health`) requires a Supabase JWT in the `Authorization` header:

```
Authorization: Bearer <supabase_access_token>
```

The backend validates the token using `SUPABASE_ANON_KEY` and extracts the `user_id` from the JWT claims. The `get_user_id` dependency handles this automatically for all router endpoints.

## Error Format

All errors follow this shape:

```json
{
  "detail": "Human-readable error message"
}
```

HTTP status codes used:
- `400` — Bad request (validation failure, missing fields)
- `401` — Missing or invalid auth token
- `404` — Resource not found
- `409` — Conflict (duplicate application, etc.)
- `500` — Internal server error

## Pagination

List endpoints that return many items use offset-based pagination:

```
GET /api/v1/jobs?offset=0&limit=20
```

Response:
```json
{
  "data": [...],
  "total": 142,
  "offset": 0,
  "limit": 20
}
```

- `limit` — max items per page (default 20, max 100)
- `offset` — number of items to skip

## Naming Conventions

- **Endpoints**: kebab-case (`/interview-prep`, `/draft-answer`, `/check-applied`)
- **JSON fields**: snake_case (`match_score`, `job_title`, `created_at`)
- **Query params**: snake_case (`min_score`, `work_mode`, `is_easy_apply`)

## Key Resources

### Jobs (`/jobs`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/jobs` | List jobs with filtering and ranking |
| GET | `/jobs/:id` | Get single job details |
| POST | `/jobs/:id/score` | Trigger AI match scoring |
| POST | `/jobs/discover` | Start background job discovery |

Query filters for `GET /jobs`:
- `query` — text search (title/company)
- `platform` — source platform filter
- `work_mode` — remote/hybrid/onsite
- `min_score` — minimum match score (default 40)
- `is_easy_apply` — boolean filter
- `show_archived` — include archived jobs

### Applications (`/applications`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/applications` | List user's applications |
| GET | `/applications/pipeline` | Get kanban board data |
| GET | `/applications/:id` | Get single application |
| PATCH | `/applications/:id` | Update application |
| POST | `/applications/:id/star` | Toggle star |
| POST | `/applications/:id/apply` | Submit application |
| POST | `/applications/:id/prepare` | Prepare assisted-apply package |
| POST | `/applications/:id/opened` | Mark as opened in browser |
| POST | `/applications/:id/confirm-submit` | Confirm submission |
| POST | `/applications/:id/mark-failed` | Record failure |
| GET | `/applications/:id/events` | Get audit trail |
| GET | `/applications/:id/interview-prep` | Get/generate interview prep |
| POST | `/applications/:id/draft-answer` | AI-draft a screening answer |
| POST | `/applications/:id/rephrase-answer` | Polish user's answer |

### Resumes (`/resumes`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/resumes/` | List user's resumes |
| POST | `/resumes/upload` | Upload resume (multipart) |
| POST | `/resumes/:id/set-primary` | Set as primary resume |
| DELETE | `/resumes/:id` | Delete a resume |
| POST | `/resumes/:id/tailor` | AI-tailor for a specific job |

### Sessions (`/sessions`)

Session-based auth for job platforms (LinkedIn, Naukri, etc.):

| Method | Path | Description |
|--------|------|-------------|
| GET | `/sessions/platforms` | List supported platforms |
| GET | `/sessions` | List user's sessions |
| POST | `/sessions/:platform/connect` | Start connection handshake |
| GET | `/sessions/handshake/:token` | Poll handshake status |
| POST | `/sessions/:platform/refresh` | Refresh session validity |
| DELETE | `/sessions/:platform` | Disconnect platform |

### Telemetry (`/telemetry`)

Mission-control observability — durable run ledger, scraper health, LLM usage. Backed by a local SQLite database (`apps/api/data/telemetry.db`), populated automatically by discovery/apply runs and every LLM call.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/telemetry/runs` | Run ledger with per-source breakdowns (`kind=discovery\|apply`, `limit`) |
| GET | `/telemetry/source-health` | Per-scraper daily yields, error rates, degradation flags (`days`, default 14) |
| GET | `/telemetry/ai-usage` | LLM usage by provider/feature, daily series, budget status (`days`) |

Daily LLM budgets are configured via `LLM_DAILY_TOKEN_BUDGET` / `LLM_DAILY_BUDGET_USD` in `.env` (0 = unlimited). Once exceeded, all LLM calls hard-stop until midnight UTC and `budget.exceeded` turns true in `/telemetry/ai-usage`.

## Database Views

### `application_details`

A PostgreSQL view joining `job_applications` with `job_listings` and `resumes`. This is the primary read source for the jobs and applications pages.

Columns come from:
- `a.*` — all columns from `job_applications` (id, user_id, match_score, status, etc.)
- `j.title AS job_title`, `j.company AS job_company`, etc. — selected job listing fields
- `j.posted_at AS job_posted_at` — requires migration `05_recency_relevance.sql`
- `r.name AS resume_name` — from the user's primary resume

If `job_posted_at` is not available (migration not applied), the backend falls back to ordering by `created_at`.

## Migration Ordering

SQL migrations in `database/` must be applied in order:

1. `schema.sql` — base tables and the `application_details` view
2. `02_automation.sql` — apply queue and automation tables
3. `03_application_tracking.sql` — submission tracking columns
4. `04_sessions.sql` — session management tables
5. `05_recency_relevance.sql` — adds `posted_at` to job_listings, updates view

## AI Provider Routing

The AI service supports multiple providers with automatic failover:

- **Groq** — primary for fast tasks (parsing, scoring)
- **NVIDIA** — fallback / reasoning tasks
- **Anthropic** — high-quality reasoning fallback

Task routing is configured in `services/ai/provider.py`. Set at least one API key in `.env`.
