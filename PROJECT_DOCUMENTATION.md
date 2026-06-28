# JobPlatform AI — Complete Project Documentation

> **AI-Powered Autonomous Job Discovery & Application Platform**
>
> This document provides a comprehensive technical reference for every subsystem,
> workflow, database table, API endpoint, and AI feature in the platform. It is
> intended for new developers joining the project, auditors reviewing system
> behavior, and maintainers planning improvements.

---

## Table of Contents

1. [High-Level Architecture](#1-high-level-architecture)
2. [End-to-End User Journey](#2-end-to-end-user-journey)
3. [Auto-Apply Engine](#3-auto-apply-engine)
4. [Application Tracking System](#4-application-tracking-system)
5. [Database Design](#5-database-design)
6. [AI Features](#6-ai-features)
7. [Job Application Process](#7-job-application-process)
8. [Backend Services](#8-backend-services)
9. [Frontend Features](#9-frontend-features)
10. [Security & Data Protection](#10-security--data-protection)
11. [Monitoring & Logging](#11-monitoring--logging)
12. [Current Limitations & Technical Debt](#12-current-limitations--technical-debt)
13. [Improvement Roadmap](#13-improvement-roadmap)
14. [Flow Diagrams](#14-flow-diagrams)

---

## 1. High-Level Architecture

### 1.1 System Overview

JobPlatform AI is a full-stack platform that autonomously discovers job listings
from 21+ sources, scores them against a user's profile using dual-LLM evaluation,
and either auto-applies or prepares an assisted-apply package for the user. The
system combines a Next.js frontend, a Python FastAPI backend, PostgreSQL with
pgvector for semantic search, Redis + Celery for background processing, and
Playwright for browser automation.

### 1.2 Component Map

```
┌──────────────────────────────────────────────────────────────────────┐
│                         USER (Browser)                               │
│  Next.js 14 Frontend — React, TypeScript, Tailwind, Three.js         │
│  Port 3000                                                           │
└──────────────────────┬───────────────────────────────────────────────┘
                       │ HTTPS (Supabase Auth JWT)
                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    FastAPI Backend (Python)                           │
│  Port 8000 — Routers: jobs, applications, resumes, ai, automation,   │
│  copilot, export, profile                                            │
│                                                                      │
│  ┌─────────────┐  ┌─────────────────┐  ┌──────────────────────┐     │
│  │ AI Service   │  │ Application Svc │  │ Notification Service │     │
│  │ (Dual LLM)   │  │ (Assisted Apply)│  │ (Email + In-App)     │     │
│  └──────┬───────┘  └────────┬────────┘  └──────────┬───────────┘     │
│         │                   │                      │                 │
└─────────┼───────────────────┼──────────────────────┼─────────────────┘
          │                   │                      │
          ▼                   ▼                      ▼
┌──────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐
│  LLM APIs    │  │  Supabase       │  │  Resend Email API           │
│  Groq (Free) │  │  PostgreSQL 15  │  └─────────────────────────────┘
│  NVIDIA (Free│  │  + pgvector     │
│  credits)    │  │  + Auth         │
└──────────────┘  │  + Storage      │
                  └────────┬────────┘
                           │
┌──────────────────────────┼──────────────────────────────────────────┐
│                   Redis + Celery                                     │
│  ┌──────────────┐  ┌──────────────────┐  ┌───────────────────────┐  │
│  │ Job Discovery │  │ Application Bot  │  │ Notification Worker   │  │
│  │ Worker        │  │ Worker           │  │                       │  │
│  │ (Every 4 hrs) │  │ (Every 30 min)   │  │ (Daily 9AM, Mon 8AM) │  │
│  └──────┬────────┘  └───────┬──────────┘  └───────────────────────┘  │
│         │                   │                                        │
│         ▼                   ▼                                        │
│  ┌─────────────────────────────────────┐                             │
│  │  21+ Job Board Scrapers             │                             │
│  │  13 Playwright (browser automation) │                             │
│  │   8 API-first (REST calls)          │                             │
│  └─────────────────────────────────────┘                             │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend** | Next.js 14.2 (App Router) | Server-side rendering, routing |
| | React 18.3 + TypeScript 5 | UI components |
| | Tailwind CSS 3.4 | Styling |
| | Zustand 4.5 | Client state management |
| | TanStack React Query 5.56 | Data fetching + caching |
| | Three.js + React Three Fiber | 3D landing page visualization |
| | Recharts 2.12 | Analytics charts |
| | Framer Motion 11.5 | Animations |
| **Backend** | Python 3.11 + FastAPI 0.115 | REST API server |
| | Celery 5.4 + Redis 7 | Task queue + scheduler |
| | Playwright 1.47 | Browser automation |
| | httpx 0.27 | Async HTTP client |
| **Database** | PostgreSQL 15 (Supabase) | Primary data store |
| | pgvector extension | Semantic vector search |
| | Supabase Auth | JWT authentication |
| | Supabase Storage | File storage (resumes, screenshots) |
| **AI/LLM** | Groq (LLaMA 3.3 70B) | Primary LLM — free tier |
| | NVIDIA NIM (Nemotron 30B) | Secondary LLM — free credits |
| | OpenAI text-embedding-3-small | Vector embeddings |
| **Email** | Resend API | Transactional email delivery |
| **Infra** | Docker Compose | Local orchestration |

### 1.4 Data Flow Summary

1. **Inbound (Job Discovery):** Celery Beat triggers discovery every 4 hours.
   Workers scrape 21+ job boards, AI parses and scores each job, results land in
   `job_listings` and `job_applications` tables.
2. **Processing (AI Scoring):** Dual-LLM evaluation: Groq and NVIDIA score each
   job independently. Scores >= 70 get double-evaluated for confidence. Tier
   assignment routes jobs to auto-apply, recommended, watchlist, or archived.
3. **Outbound (Application):** Auto-apply tier jobs are queued and submitted via
   Playwright. Recommended tier jobs wait for user approval. Assisted-apply
   builds a package (cover letter, answers, form data) and opens the external
   page for the user.
4. **Tracking:** Every status change is logged in `application_status_history`.
   Every workflow step is logged in `application_events`. The user sees a Kanban
   pipeline view and detailed event timeline.

---

## 2. End-to-End User Journey

### 2.1 Sign-Up and Profile Configuration

```
User visits /              → Landing page with 3D career universe
  ↓
Clicks "Get Started"       → Redirected to /auth/login
  ↓
Google OAuth via Supabase   → auth/callback/route.ts exchanges code for session
  ↓
First visit detected        → /settings page for profile setup
  ↓
User fills profile:
  - Full name, headline, location, phone
  - LinkedIn, GitHub, portfolio URLs
  - Years of experience, current salary, expected salary range
  - Skills array, per-skill years of experience (tech_stack JSONB)
  - Career goals (free text)
  - Preferred work modes, job types, locations
  - Notice period, work authorization
  - Auto-apply toggle + threshold (default 80%)
  - Preferred job platforms
  ↓
Profile saved to users table → is_onboarded = true
```

### 2.2 Resume Upload and Profile Extraction

```
User navigates to /resume   → Resume upload page
  ↓
Drag-and-drop PDF/DOCX      → POST /api/v1/resumes/upload (multipart)
  ↓
Backend:
  1. Validate file type (PDF or DOCX)
  2. Extract raw text (PyPDF2 for PDF, python-docx for DOCX)
  3. Upload file to Supabase Storage (resumes bucket)
  4. Send text to LLM for structured parsing
  ↓
AI extracts ParsedResume:
  - full_name, email, phone, location
  - linkedin_url, github_url, portfolio_url
  - summary (professional summary paragraph)
  - skills[] (flat list of all skills)
  - tech_stack{} (skill → years of experience)
  - experience[] (company, title, dates, description, achievements, skills_used)
  - education[] (institution, degree, field, GPA, achievements)
  - projects[] (name, description, tech_stack, URL, achievements)
  - certifications[], languages[]
  - total_experience_years
  ↓
Backend:
  5. Store parsed_data JSONB in resumes table
  6. Compute word_count and ats_score
  7. Sync extracted skills to user.skills[] (additive merge)
  8. Sync tech_stack to user.tech_stack{} (update missing entries)
  9. Mark as is_primary if user's first resume
  ↓
Frontend displays parsed results with edit capability
```

### 2.3 Job Search and Job Matching

```
User triggers discovery:
  Option A: Click "Discover Jobs" on /jobs page → POST /api/v1/jobs/discover
  Option B: Automatic via Celery Beat every 4 hours (if auto_apply_enabled)
  ↓
Discovery Worker (see Section 3 for full detail):
  1. Load user profile (skills, headline, career goals, preferences)
  2. Build search queries from user headline + skills + career goals
  3. Select sources for user's region (India / Global)
  4. Scrape 21+ job boards concurrently
  5. Deduplicate by source_url + filter blacklisted companies
  6. Batch parse JDs via dual-LLM (Groq + NVIDIA)
  7. Batch score against user profile (dual-LLM with double-eval for top matches)
  8. Assign tiers: auto_apply >= 80, recommended 60-79, watchlist 50-59, archived < 50
  9. Store in job_listings + job_applications tables
  10. Queue auto_apply tier for submission (if auto_apply_enabled)
  11. Create notifications for new matches
  ↓
User views results on /jobs page:
  - Grid of job cards with company, title, location, salary, match score
  - Filter by platform, work mode, salary range, match score
  - Click card for full job details + match analysis
```

### 2.4 Job Scoring and Ranking

Scoring is a two-phase process:

**Phase 1: Batch Evaluation**
- Jobs are distributed round-robin across Groq and NVIDIA
- Each LLM evaluates candidate-job fit on a 0-100 scale
- Score breakdown: skills_match (40%), experience_match (30%), role_fit (20%),
  culture_location_fit (10%)
- 4 concurrent evaluations (semaphore-limited for free tier friendliness)

**Phase 2: Double Evaluation (Confidence Scoring)**
- Jobs scoring >= 70 in Phase 1 are re-evaluated by the *other* provider
- Final score = average of both providers
- Score spread metric tracks inter-provider agreement
- Strengths and gaps are merged and deduplicated

### 2.5 Application Tracking

```
User views pipeline on /dashboard → Kanban board with 6 columns:
  - Matched (discovered, matched, queued)
  - Applied (applying, applied)
  - In Progress (under_review, assessment)
  - Interviews (interview_scheduled, technical_round, hr_round)
  - Offers (offer_received, accepted)
  - Closed (rejected, withdrawn)

User can:
  - Drag cards between columns (status update)
  - Star important applications
  - Add notes and interview details
  - View full audit trail (event timeline)
  - Export data as CSV or Excel
```

---

## 3. Auto-Apply Engine

### 3.1 Job Discovery

#### Source Registry (21 Sources)

**Browser-Based Scrapers (Playwright — 13 sources):**

| Source | Region | Login-Capable | Rate Limit |
|--------|--------|--------------|------------|
| LinkedIn | India + Global | Yes | 10/min |
| Naukri | India | Yes | 15/min |
| Indeed | India + Global | Yes | 20/min |
| Instahyre | India | Yes | Default |
| Hirist | India | No | Default |
| Cutshort | India | No | Default |
| Foundit | India | No | Default |
| Wellfound | India + Global | No | Default |
| Glassdoor | Global | No | Default |
| Dice | Global | No | Default |
| ZipRecruiter | Global | No | Default |
| WeWorkRemotely | Global | No | Default |
| RemoteOK | Global + India | No | Default |

**API-First Scrapers (HTTP — 8 sources):**

| Source | Region | Key Required | Notes |
|--------|--------|-------------|-------|
| Remotive | Global + India | No | Free API, remote-focused |
| Arbeitnow | Global | No | Free API, 70+ countries |
| TheMuse | Global + India | No | Free API, startup jobs |
| Adzuna | India + Global | Yes (APP_ID + KEY) | Structured salary data |
| Jooble | India + Global | Yes | ~70 countries |
| JSearch | India + Global | Yes (RapidAPI) | Google-for-Jobs aggregator |

#### Source Selection Logic

```python
def select_sources(region, preferred_platforms):
    # 1. Always include: API-first keyless sources serving the region
    # 2. Include: API-first keyed sources IF key is configured
    # 3. Include: Playwright sources ONLY if user opted in (preferred_platforms)
    # 4. Exclude: sources not serving the region
    # 5. Exclude: keyed sources without valid keys
```

#### Search Query Construction

```
Queries derived from user profile (up to 3 unique queries):
  1. First part of headline (before "·" separator)
  2. First 3 skills joined: "Python React TypeScript"
  3. First 50 chars of career_goals
  Fallback: "software developer"
```

### 3.2 Job Filtering

Before scoring, raw jobs are filtered:

1. **URL Deduplication:** Jobs already in `job_applications` for this user are
   skipped (matched by `source_url` via `job_listings`).
2. **Company Blacklist:** Jobs from companies in the user's `company_blacklist`
   table are excluded (case-insensitive match).
3. **Database Constraint:** `job_listings.source_url` is UNIQUE — duplicate job
   posts from the same URL are upserted, not duplicated.

### 3.3 Job Ranking

After scoring, jobs are ranked and tiered:

| Tier | Score Range | Behavior |
|------|------------|----------|
| `auto_apply` | >= 80 (configurable per user) | Queued for auto-submission if `auto_apply_enabled` |
| `recommended` | 60-79 | Shown on /approve page; user must approve before apply |
| `watchlist` | 50-59 | Visible on /jobs page; informational only |
| `archived` | < 50 | Hidden from main views |

Within each tier, jobs are sorted by `match_score DESC`.

### 3.4 Auto-Apply Selection

A job is selected for auto-application when ALL conditions are met:
1. `match_score >= user.auto_apply_threshold` (default 80)
2. `match_tier == 'auto_apply'`
3. `user.auto_apply_enabled == true`
4. Job company is NOT in user's blacklist
5. No existing application for this user + job pair (UNIQUE constraint)

### 3.5 Duplicate Prevention

Duplicates are prevented at three levels:

1. **Job Listing Level:** `job_listings.source_url` has a UNIQUE constraint.
   Same URL from different discovery runs is upserted (updated, not duplicated).
2. **Application Level:** `job_applications(user_id, job_listing_id)` has a
   UNIQUE index. A user can never have two application records for the same job.
   Discovery uses `UPSERT ... ON CONFLICT` to update scores if re-discovered.
3. **Pre-Discovery Check:** Before scraping, the worker loads all existing
   `source_url` values for the user's applications and skips any matching URLs
   from scraper results.

### 3.6 Pre-Submission Workflow

Before any application is submitted (auto or assisted):

```
1. VALIDATE PROFILE — Required fields check:
   - full_name, email, phone, location
   - experience_years, expected_salary_min
   - work_authorization, notice_period_days
   → If any missing: return {needs_input: [...]} — BLOCK, never guess

2. VALIDATE SKILL EXPERIENCE — For skills the job requires:
   - Check user.tech_stack{skill: years} for each relevant skill
   → If any missing: return {needs_input: [...]} — BLOCK, never guess

3. RESOLVE RESUME:
   - Use override resume_id if provided
   - Else use user's primary resume (is_primary = true)
   - Else use most recently uploaded active resume
   → If none: return {needs_input: [{field: "resume"}]}

4. GENERATE COVER LETTER:
   - AI generates from REAL user data only (anti-fabrication enforced)
   - 3 paragraphs, < 350 words, first person

5. DRAFT SCREENING ANSWERS:
   - Pre-draft 5 common questions using user's real profile data
   - If AI cannot answer truthfully (missing data): return [NEEDS_INFO]
   - Collect missing answers from user before proceeding

6. ASSEMBLE PACKAGE:
   - form_data: all profile fields snapshot
   - resume_snapshot: resume ID, name, URL, version
   - job_snapshot: job title, company, URL, salary, platform
   - submitted_responses: screening answers
```

### 3.7 Submission Process

**Auto-Apply (Fully Automated):**

```
1. Worker picks from apply_queue (priority-ordered)
2. Mark queue item status = "running", increment attempts
3. Mark application status = "applying"
4. Download user's primary resume to temp file
5. Generate cover letter via AI
6. Route to platform-specific scraper:

   LinkedIn Easy Apply:
     a. Launch headless Chromium via Playwright
     b. Login with stored credentials
     c. Navigate to job URL
     d. Click "Easy Apply" button
     e. Fill multi-step form (name, email, phone, resume upload)
     f. Answer screening questions via AI callback
     g. Submit application
     h. Capture confirmation ID

   Naukri:
     a. Login to Naukri with credentials
     b. Navigate to job page
     c. Click apply button
     d. Handle form if present

   Generic Portal:
     a. Open apply_url in headless browser
     b. Detect form fields (name, email, phone, file input)
     c. Fill detected fields with user profile data
     d. Upload resume if file input found
     e. Click submit button

7. On SUCCESS:
   - Update application: status = "applied", applied_via = "auto"
   - Record applied_at timestamp and application_id
   - Mark queue item completed
   - Send email + in-app notification to user

8. On FAILURE:
   - Revert application status to "matched"
   - If attempts < max_attempts (3): re-queue with "pending" status
   - If attempts >= max_attempts: mark queue item "failed"
   - Log error message
   - Clean up temp files
```

**Assisted-Apply (User-Guided):**

```
1. User clicks "Apply" on /applications page
2. POST /api/v1/applications/{id}/prepare
3. Backend builds package (cover letter, answers, form data)
4. If {needs_input}: frontend shows form for missing fields
5. User reviews/edits cover letter and screening answers
6. User clicks "Open Application" → opens external apply URL
7. POST /api/v1/applications/{id}/opened (audit event logged)
8. User completes application on external site manually
9. User clicks "Confirm Submitted" or "Mark Failed"
10. POST /api/v1/applications/{id}/confirm-submit
    - Status → "applied", submission_status → "submitted"
    OR
    POST /api/v1/applications/{id}/mark-failed
    - Status → "matched" (reverted), submission_status → "failed"
```

### 3.8 Retry Mechanism and Failure Handling

```
apply_queue table:
  - attempts: current attempt count (starts at 0)
  - max_attempts: default 3
  - status: pending → running → completed | failed
  - error_msg: last error message (truncated to 500 chars)
  - next_attempt_at: when to retry (used by Celery Beat polling)

Retry Logic:
  - After failure with attempts < max_attempts:
    status = "pending", error_msg recorded
  - After failure with attempts >= max_attempts:
    status = "failed", application status reverted to "matched"
  - Celery Beat processes queue every 30 minutes:
    picks pending items where next_attempt_at <= now()

AI Service Retries:
  - Rate limit (429) errors: exponential backoff [2s, 4s, 8s]
  - Provider failure: automatic failover to other provider
  - Both providers fail: return empty defaults (never crash)
```

---

## 4. Application Tracking System

### 4.1 Application Status Lifecycle

```
                              ┌──────────┐
                              │discovered│ (initial scrape, no scoring yet)
                              └────┬─────┘
                                   │ AI scores job
                                   ▼
                              ┌──────────┐
                              │ matched  │ (scored, tier assigned)
                              └────┬─────┘
                                   │ queued for auto-apply
                                   ▼
                              ┌──────────┐
                              │  queued  │ (in apply_queue, awaiting worker)
                              └────┬─────┘
                                   │ worker picks up
                                   ▼
                              ┌──────────┐
                              │ applying │ (submission in progress)
                              └────┬─────┘
                          ┌────────┴────────┐
                     success              failure
                          ▼                    ▼
                    ┌──────────┐         reverts to
                    │ applied  │         "matched"
                    └────┬─────┘
                         │ employer responds
                         ▼
              ┌──────────────────────┐
              │    under_review      │
              └──────────┬───────────┘
                         │
              ┌──────────┴───────────┐
              ▼                      ▼
        ┌───────────┐         ┌───────────┐
        │assessment │         │ rejected  │
        └─────┬─────┘         └───────────┘
              │
              ▼
     ┌────────────────────┐
     │interview_scheduled │
     └────────┬───────────┘
              │
     ┌────────┴────────┐
     ▼                 ▼
┌──────────────┐ ┌──────────┐
│technical_round│ │ hr_round │
└──────┬───────┘ └────┬─────┘
       │               │
       └───────┬───────┘
               ▼
        ┌──────────────┐
        │offer_received│
        └──────┬───────┘
               │
        ┌──────┴──────┐
        ▼             ▼
   ┌─────────┐  ┌──────────┐
   │accepted │  │ withdrawn│ (can happen at any stage)
   └─────────┘  └──────────┘
```

### 4.2 Database Records Created During Application

When an application is submitted, the following records are created or updated:

| Table | Record | When |
|-------|--------|------|
| `job_listings` | Job details (upsert by source_url) | During discovery |
| `job_applications` | Application record with match_score, tier, analysis | During discovery |
| `application_status_history` | Status change from "matched" → "queued" | When queued |
| `apply_queue` | Queue item with priority, attempts | When queued |
| `application_events` | "prepared" event with metadata | During prepare step |
| `application_events` | "cover_letter_generated" event | After cover letter AI call |
| `application_events` | "answers_drafted" event | After screening answers drafted |
| `application_events` | "opened_external" event | When user opens external page |
| `application_events` | "submitted" event with confirmation_id | When submission confirmed |
| `application_status_history` | Status change to "applied" | On submission |
| `notifications` | "application_submitted" notification | On successful submission |

### 4.3 Application Status Storage

```sql
-- Primary status tracking
job_applications.status (ENUM): 14 possible values
job_applications.applied_at (TIMESTAMPTZ): when submitted
job_applications.applied_via (TEXT): "auto" | "assisted" | "manual"

-- Extended tracking (Migration 03)
job_applications.submission_status (TEXT):
  "not_started" | "ready" | "opened" | "submitted" | "failed"
job_applications.submission_method (TEXT):
  "assisted" | "auto" | "manual"
job_applications.form_data (JSONB): snapshot of all form fields at submission
job_applications.submitted_responses (JSONB): screening answers submitted
job_applications.job_snapshot (JSONB): job details at submission time
job_applications.resume_snapshot (JSONB): resume metadata at submission time
job_applications.failure_reason (TEXT): why submission failed
job_applications.prepared_at (TIMESTAMPTZ): when package was assembled
```

### 4.4 How Users Verify Applications

Users can verify that a job was actually applied to through:

1. **Kanban Dashboard (/dashboard):** Applications in "Applied" column have
   `status = "applied"` and `applied_at` timestamp.
2. **Application Detail View:** Shows `applied_via` (auto/assisted/manual),
   `applied_at` timestamp, and `application_id` (external confirmation ID).
3. **Event Timeline (/applications/{id}/events):** Ordered list of every
   workflow step: prepared → cover_letter_generated → answers_drafted →
   opened_external → submitted. Each event has a timestamp and metadata.
4. **Status History (/applications/{id}/history):** Every status transition
   logged with old_status, new_status, changed_by, and timestamp.
5. **Submission Snapshots:** `form_data`, `submitted_responses`, `job_snapshot`,
   and `resume_snapshot` JSONB fields capture exactly what was submitted and when.

### 4.5 Audit Trail Design

Two complementary audit systems:

**application_status_history** — Tracks status transitions:
```sql
application_id  → which application
old_status      → previous status (NULL for initial)
new_status      → new status
changed_by      → "system" or "user"
note            → optional explanation
metadata        → JSONB additional context
changed_at      → timestamp
-- Populated automatically via trigger on job_applications.status UPDATE
```

**application_events** — Tracks workflow steps:
```sql
application_id  → which application
user_id         → which user
event_type      → prepared | cover_letter_generated | answers_drafted |
                   opened_external | submitted | failed | status_changed |
                   user_confirmed | note
message         → human-readable description
metadata        → JSONB (e.g., missing fields, confirmation_id)
created_at      → timestamp
-- Populated by application_service.log_event() at each workflow step
```

### 4.6 Failed Application Tracking and Retry

```
On Failure:
  1. application status reverted to "matched" (so user can re-try)
  2. apply_queue.status = "failed" (if max attempts reached) or "pending" (if retries remain)
  3. apply_queue.error_msg = first 500 chars of error
  4. application_events log: event_type = "failed", message = reason
  5. submission_status = "failed", failure_reason = reason

Retry:
  - Celery Beat checks apply_queue every 30 minutes
  - Picks items where status = "pending" AND next_attempt_at <= now()
  - Processes in priority order (lower number = higher priority)
  - Max 3 attempts per job (configurable via max_attempts)
```

---

## 5. Database Design

### 5.1 Complete Schema Overview

The database uses PostgreSQL 15 with three extensions:
- `uuid-ossp` — UUID generation
- `pgcrypto` — Encryption functions
- `vector` (pgvector) — 1536-dimensional vector storage and similarity search

### 5.2 Enums

```sql
application_status: discovered, matched, queued, applying, applied,
                    under_review, assessment, interview_scheduled,
                    technical_round, hr_round, offer_received,
                    rejected, withdrawn, accepted

match_tier:         auto_apply, recommended, watchlist, archived

platform:           linkedin, naukri, indeed, wellfound, hirist,
                    instahyre, cutshort, glassdoor, foundit, remoteok,
                    weworkremotely, dice, ziprecruiter, angellist,
                    remotive, arbeitnow, themuse, adzuna, jooble,
                    jsearch, company_portal, other

work_mode:          remote, hybrid, onsite
job_type:           full_time, part_time, contract, freelance, internship
experience_level:   entry, mid, senior, lead, principal, executive

notification_type:  application_submitted, job_match, interview_scheduled,
                    assessment_received, offer_received, rejection,
                    follow_up_reminder, profile_suggestion, skill_gap
```

### 5.3 Table Details

#### users
**Purpose:** Stores user profile, career preferences, and automation settings.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | References auth.users(id) |
| email | TEXT UNIQUE NOT NULL | |
| full_name | TEXT | |
| avatar_url | TEXT | |
| headline | TEXT | e.g., "Senior Backend Engineer · Python · 5y" |
| location | TEXT | |
| phone | TEXT | |
| linkedin_url, github_url, portfolio_url | TEXT | |
| experience_years | INTEGER | |
| current_salary | INTEGER | |
| expected_salary_min, expected_salary_max | INTEGER | |
| preferred_locations | TEXT[] | |
| preferred_work_modes | work_mode[] | |
| preferred_job_types | job_type[] | |
| open_to_remote | BOOLEAN | Default true |
| notice_period_days | INTEGER | Default 30 |
| skills | TEXT[] | Flat list of all skills |
| tech_stack | JSONB | {skill: years_of_experience} |
| career_goals | TEXT | Free text |
| auto_apply_enabled | BOOLEAN | Default false |
| auto_apply_threshold | INTEGER | Default 80 |
| preferred_platforms | platform[] | |
| is_onboarded | BOOLEAN | |
| work_authorization | TEXT | Added in migration 03 |
| willing_to_relocate | BOOLEAN | Added in migration 03 |
| created_at, updated_at | TIMESTAMPTZ | |

#### resumes
**Purpose:** Stores uploaded resume files and AI-parsed structured data.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | Auto-generated |
| user_id | UUID FK → users | |
| name | TEXT NOT NULL | Original filename |
| file_url | TEXT NOT NULL | Supabase Storage URL |
| file_size | INTEGER | Bytes |
| file_type | TEXT | Default 'application/pdf' |
| is_primary | BOOLEAN | Unique per user (enforced by trigger) |
| is_active | BOOLEAN | Soft delete flag |
| parsed_data | JSONB | Full ParsedResume structure |
| ats_score | INTEGER | 0-100 ATS compatibility estimate |
| word_count | INTEGER | |
| version | INTEGER | Default 1 |
| created_at, updated_at | TIMESTAMPTZ | |

**Constraints:** Unique partial index on (user_id) WHERE is_primary = TRUE.
**Trigger:** `enforce_single_primary_resume()` — ensures at most one primary per user.

#### job_listings
**Purpose:** Stores discovered job postings from all sources.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | Auto-generated |
| title | TEXT NOT NULL | |
| company | TEXT NOT NULL | |
| company_logo_url | TEXT | |
| company_website | TEXT | |
| location | TEXT | |
| work_mode | work_mode ENUM | |
| job_type | job_type ENUM | Default 'full_time' |
| experience_level | experience_level ENUM | |
| min_experience, max_experience | INTEGER | Years |
| salary_min, salary_max | INTEGER | |
| salary_currency | TEXT | Default 'INR' |
| jd_text | TEXT NOT NULL | Raw job description |
| jd_html | TEXT | HTML version if available |
| required_skills | TEXT[] | |
| nice_to_have_skills | TEXT[] | |
| source_platform | platform ENUM NOT NULL | |
| source_url | TEXT NOT NULL UNIQUE | Deduplication key |
| source_job_id | TEXT | Platform's internal ID |
| apply_url | TEXT | Direct application URL |
| application_deadline | TIMESTAMPTZ | |
| is_easy_apply | BOOLEAN | Default false |
| is_active | BOOLEAN | Default true |
| is_remote_friendly | BOOLEAN | |
| views_count | INTEGER | |
| applicants_count | INTEGER | |
| hiring_manager | TEXT | |
| hiring_manager_url | TEXT | |
| company_size | TEXT | |
| company_industry | TEXT | |
| discovered_at, last_seen_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ | |

**Indexes:** source_platform, is_active, discovered_at DESC, required_skills (GIN).

#### job_embeddings / user_embeddings
**Purpose:** pgvector embeddings for semantic similarity matching.

| Column | Type | Notes |
|--------|------|-------|
| job_listing_id / user_id | UUID PK | FK to respective table |
| embedding | vector(1536) | OpenAI text-embedding-3-small |
| model | TEXT | Default 'text-embedding-3-small' |
| created_at / updated_at | TIMESTAMPTZ | |

**Index:** ivfflat with vector_cosine_ops (lists = 100) for fast similarity search.

#### job_applications
**Purpose:** Central table tracking every user-job relationship from discovery through offer.

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| user_id | UUID FK → users | |
| job_listing_id | UUID FK → job_listings | |
| resume_id | UUID FK → resumes | Optional |
| match_score | INTEGER | 0-100 |
| match_tier | match_tier ENUM | auto_apply / recommended / watchlist / archived |
| match_analysis | JSONB | Strengths, gaps, recommendations, score_breakdown |
| skill_gaps | TEXT[] | Required skills the user lacks |
| missing_skills | TEXT[] | Nice-to-have skills missing |
| status | application_status ENUM | 14-state lifecycle |
| cover_letter | TEXT | Generated cover letter text |
| cover_letter_url, tailored_resume_url | TEXT | |
| applied_at | TIMESTAMPTZ | |
| application_id | TEXT | External confirmation ID |
| confirmation_screenshot_url | TEXT | |
| applied_via | TEXT | "auto", "assisted", or "manual" |
| interview_date | TIMESTAMPTZ | |
| interview_notes, interviewer_name | TEXT | |
| offered_salary | INTEGER | |
| offer_deadline | TIMESTAMPTZ | |
| is_starred | BOOLEAN | |
| notes | TEXT | |
| rejection_reason | TEXT | |
| follow_up_at | TIMESTAMPTZ | |
| submission_status | TEXT | not_started / ready / opened / submitted / failed |
| submission_method | TEXT | assisted / auto / manual |
| form_data | JSONB | Profile snapshot at submission time |
| submitted_responses | JSONB | Screening answers submitted |
| job_snapshot | JSONB | Job details at submission time |
| resume_snapshot | JSONB | Resume details at submission time |
| failure_reason | TEXT | |
| prepared_at | TIMESTAMPTZ | |
| created_at, updated_at | TIMESTAMPTZ | |

**Constraints:** UNIQUE(user_id, job_listing_id).
**Indexes:** user_id, status, match_score DESC, applied_at DESC.
**Trigger:** `track_application_status_change()` → logs to application_status_history.

#### application_status_history
**Purpose:** Immutable audit log of every status transition.

| Column | Type |
|--------|------|
| id | UUID PK |
| application_id | UUID FK → job_applications |
| old_status | application_status ENUM (nullable for first entry) |
| new_status | application_status ENUM |
| changed_by | TEXT (default 'system') |
| note | TEXT |
| metadata | JSONB |
| changed_at | TIMESTAMPTZ |

#### application_events
**Purpose:** Detailed workflow audit trail (added in migration 03).

| Column | Type |
|--------|------|
| id | UUID PK |
| application_id | UUID FK → job_applications |
| user_id | UUID FK → users |
| event_type | TEXT |
| message | TEXT |
| metadata | JSONB |
| created_at | TIMESTAMPTZ |

#### interview_prep
**Purpose:** AI-generated interview preparation materials per application.

| Column | Type |
|--------|------|
| id | UUID PK |
| application_id | UUID FK (UNIQUE) |
| user_id | UUID FK |
| technical_questions | JSONB array |
| behavioral_questions | JSONB array |
| system_design_questions | JSONB array |
| coding_challenges | JSONB array |
| company_research | JSONB |
| preparation_plan | TEXT (markdown) |
| key_talking_points | TEXT[] |
| salary_negotiation | JSONB |
| completed_questions, total_questions, prep_score | INTEGER |
| last_practiced_at | TIMESTAMPTZ |
| generated_at, updated_at | TIMESTAMPTZ |

#### platform_credentials
**Purpose:** Encrypted login credentials for job boards.

| Column | Type |
|--------|------|
| id | UUID PK |
| user_id | UUID FK |
| platform | platform ENUM |
| encrypted_username | TEXT |
| encrypted_password | TEXT |
| oauth_token | TEXT |
| session_cookies | JSONB |
| is_verified | BOOLEAN |
| last_used_at, last_verified_at | TIMESTAMPTZ |

**Constraint:** UNIQUE(user_id, platform).

#### notifications
**Purpose:** In-app and email notification records.

| Column | Type |
|--------|------|
| id | UUID PK |
| user_id | UUID FK |
| type | notification_type ENUM |
| title | TEXT |
| body | TEXT |
| payload | JSONB |
| action_url | TEXT |
| is_read | BOOLEAN |
| is_sent_email | BOOLEAN |
| email_sent_at, read_at | TIMESTAMPTZ |
| created_at | TIMESTAMPTZ |

#### apply_queue
**Purpose:** Task queue for auto-apply worker.

| Column | Type |
|--------|------|
| id | UUID PK |
| application_id | UUID FK |
| user_id | UUID FK |
| priority | INTEGER (1-10, lower = higher) |
| attempts | INTEGER (default 0) |
| max_attempts | INTEGER (default 3) |
| status | TEXT (pending/running/completed/failed) |
| error_msg | TEXT |
| next_attempt_at | TIMESTAMPTZ |
| started_at, completed_at | TIMESTAMPTZ |

**Index:** (status, next_attempt_at) for worker polling.

#### discovery_queue
**Purpose:** Tracks job search operations.

| Column | Type |
|--------|------|
| id | UUID PK |
| user_id | UUID FK |
| search_query | TEXT |
| platform | platform ENUM |
| status | TEXT |
| jobs_found, jobs_matched | INTEGER |
| error_msg | TEXT |
| started_at, completed_at | TIMESTAMPTZ |

#### analytics_snapshots
**Purpose:** Daily aggregated metrics per user.

| Column | Type |
|--------|------|
| id | UUID PK |
| user_id | UUID FK |
| snapshot_date | DATE |
| total_applied, total_matched, total_interviews, total_offers, total_rejected | INTEGER |
| response_rate, interview_rate, offer_rate | NUMERIC(5,2) |
| platform_breakdown | JSONB |
| skill_demand | JSONB |
| avg_match_score | NUMERIC(5,2) |

**Constraint:** UNIQUE(user_id, snapshot_date).

#### company_blacklist
**Purpose:** Per-user list of companies to never apply to.

| Column | Type |
|--------|------|
| id | UUID PK |
| user_id | UUID FK |
| company_name | TEXT |

**Constraint:** UNIQUE(user_id, LOWER(company_name)).

### 5.4 Views

**application_details** — Joins applications + job_listings + resumes:
```sql
SELECT a.*, j.title AS job_title, j.company AS job_company,
       j.company_logo_url, j.location AS job_location,
       j.work_mode, j.job_type, j.salary_min, j.salary_max,
       j.salary_currency, j.source_platform, j.source_url,
       j.apply_url, j.is_easy_apply, j.required_skills, j.jd_text,
       r.name AS resume_name, r.file_url AS resume_url
FROM job_applications a
JOIN job_listings j ON a.job_listing_id = j.id
LEFT JOIN resumes r ON a.resume_id = r.id;
```

### 5.5 Functions

- `update_updated_at()` — Trigger function: sets updated_at = NOW() on row update
- `track_application_status_change()` — Trigger function: logs status transitions
- `enforce_single_primary_resume()` — Trigger function: ensures one primary resume per user
- `get_pipeline_stats(user_id)` — Returns (status, count) aggregates for Kanban
- `find_similar_jobs(user_id, limit)` — Semantic search via pgvector cosine similarity

---

## 6. AI Features

### 6.1 LLM Provider Architecture

The platform uses a **dual-provider architecture** for cost efficiency and reliability:

```
                    ┌──────────────────┐
                    │  _call_llm()     │
                    │  Smart Router    │
                    └────────┬─────────┘
                             │
              ┌──────────────┴──────────────┐
              │ Round-robin + rate-limit     │
              │ awareness + failover         │
              ▼                              ▼
    ┌─────────────────┐           ┌─────────────────┐
    │  Groq            │           │  NVIDIA NIM      │
    │  LLaMA 3.3 70B  │           │  Nemotron 30B    │
    │  ~30 RPM (free)  │           │  ~20 RPM (free)  │
    └─────────────────┘           └─────────────────┘
```

**Provider Selection:**
- Round-robin across providers with valid API keys
- Per-provider rate tracking (60-second sliding window)
- Automatic failover: if primary fails, retry with next available
- `prefer=["groq"]` parameter pins free-text outputs to non-reasoning model
  to prevent chain-of-thought leakage

**Batch Processing:**
- `asyncio.Semaphore(4)` limits concurrency for free-tier friendliness
- Exponential backoff on 429 errors: [2s, 4s, 8s]
- Cross-provider failover per individual job in batch

### 6.2 Resume Parsing

**Input:** Raw text extracted from PDF/DOCX

**LLM Prompt:** Instructs AI to extract structured data into a ParsedResume schema.

**Output:**
```json
{
  "full_name": "string",
  "email": "string",
  "phone": "string",
  "location": "string",
  "summary": "Professional summary paragraph",
  "skills": ["Python", "React", "AWS"],
  "tech_stack": {"Python": 5, "React": 3},
  "experience": [
    {
      "company": "Acme Corp",
      "title": "Senior Engineer",
      "start_date": "2020-01",
      "end_date": "2023-12",
      "description": "Led backend team...",
      "achievements": ["Reduced latency by 40%"],
      "skills_used": ["Python", "PostgreSQL"]
    }
  ],
  "education": [...],
  "projects": [...],
  "certifications": [...],
  "total_experience_years": 5
}
```

**Post-Processing:** Extracted skills and tech_stack are synced to the user profile (additive merge — never removes existing data).

### 6.3 Job Matching and Scoring

**Two-Stage Scoring:**

**Stage 1: Batch Evaluation (all jobs)**
```
System: "You are an expert career AI that evaluates candidate-job fit."

Input:
  CANDIDATE: skills, tech_stack, experience_years, headline, career_goals
  JOB: title, company, required_skills, nice_to_have, experience level
  JD excerpt (3000 chars)

Output (JSON):
  overall_score: 0-100
  score_breakdown:
    skills_match: 0-40     (weight: 40%)
    experience_match: 0-30  (weight: 30%)
    role_fit: 0-20          (weight: 20%)
    culture_location_fit: 0-10 (weight: 10%)
  matched_skills: [...]
  missing_required_skills: [...]
  strengths: ["top 3-5 strengths"]
  gaps: ["top 3-5 gaps"]
  recommendations: ["actionable improvements"]
  summary: "2-3 sentence honest assessment"
  tier: auto_apply | recommended | watchlist | archived
```

**Stage 2: Double Evaluation (high-scoring jobs >= 70)**
```
1. Job scored 75 by Groq → qualifies for double-eval
2. Same prompt sent to NVIDIA
3. NVIDIA scores it 81
4. Final score = average(75, 81) = 78
5. Score spread = |75 - 81| = 6 (good agreement)
6. Strengths/gaps merged and deduplicated
7. Tier re-evaluated on averaged score
```

### 6.4 Cover Letter Generation

**System Prompt:**
```
You are an expert career coach who writes authentic cover letters.
Write in first person. Be specific and concrete. Avoid cliches. Max 350 words.

ANTI-FABRICATION RULES (strict):
- Use ONLY facts present in the CANDIDATE data / resume summary below.
- NEVER invent employers, projects, metrics, years, titles, or achievements
  that are not explicitly provided.
- Every concrete claim must trace to provided data.
```

**Input:** User profile + resume summary + job details
**Output:** 3-paragraph letter (interest → skills connection → close)
**Provider:** Pinned to Groq (non-reasoning) to prevent chain-of-thought leakage

### 6.5 Screening Question Answering

Two modes:

**Strict Mode** (`answer_screening_question`):
- Used for auto-apply submissions
- Returns ONLY facts from user data
- If data is missing: returns `[NEEDS_INFO] what specific info is needed`
- Never fabricates — missing data always surfaces to user

**Permissive Mode** (`draft_answer_for_user`):
- Used for user-reviewed drafts
- Can reason about fit/motivation from user's background
- Still cannot invent factual claims
- Output wrapped in `<ANSWER>` tags to separate from reasoning

**Answer Rephrasing** (`rephrase_answer`):
- Polish grammar, clarity, professional tone
- Preserve meaning and intent — no new facts
- Keep approximately same length (within 25%)

### 6.6 Answer Extraction Pipeline

LLM responses (especially from reasoning models) may contain chain-of-thought,
`<think>` blocks, or truncated `<ANSWER>` tags. The extraction pipeline handles all cases:

```
1. Check for <ANSWER>...</ANSWER> tags → extract content
2. Check for lone <ANSWER> (truncated response) → extract everything after
3. Strip <think> blocks
4. Look for "Final answer:" / "Answer:" / "Output:" markers → extract after
5. Find largest quoted block (reasoning models often wrap in quotes)
6. Fall back to cleaned raw text
7. Final cleanup: strip quotes, remove leftover tag fragments
```

### 6.7 Interview Preparation

**Input:** User profile + job details + match analysis (strengths/gaps)

**Output:**
```json
{
  "technical_questions": [
    {"question": "...", "ideal_answer": "...", "difficulty": "medium", "topic": "System Design"}
  ],
  "behavioral_questions": [
    {"question": "...", "ideal_answer": "STAR format answer", "competency": "Leadership"}
  ],
  "system_design_questions": [
    {"question": "...", "approach": "...", "key_points": ["..."]}
  ],
  "coding_challenges": [
    {"title": "...", "description": "...", "hints": ["..."], "topics": ["..."]}
  ],
  "company_research": {
    "known_products": ["..."],
    "culture_notes": "...",
    "recent_news": "...",
    "interview_style": "...",
    "questions_to_ask": ["..."]
  },
  "key_talking_points": ["..."],
  "preparation_plan": "Day-by-day markdown plan",
  "salary_negotiation": {
    "target_range": "...",
    "anchor_strategy": "...",
    "talking_points": ["..."]
  }
}
```

### 6.8 Skill Gap Analysis

**Input:** User profile + 100 recent job listings from discovery

**Process:**
1. Aggregate required_skills across all JDs → frequency-ranked demand map
2. Compare against user's skills array
3. LLM analyzes gaps with market context

**Output:**
```json
{
  "missing_skills": [
    {
      "skill": "Kubernetes",
      "demand_score": 85,
      "salary_impact_percent": 15,
      "difficulty": "medium",
      "time_to_learn_weeks": 6,
      "resources": [
        {"type": "course", "name": "CKA Prep", "url": "...", "free": true}
      ],
      "why_important": "Required in 85% of DevOps roles..."
    }
  ],
  "trending_skills": ["..."],
  "market_insights": {
    "hottest_tech_stack": "...",
    "declining_skills": ["..."],
    "salary_trends": "...",
    "hiring_trend": "..."
  },
  "priority_recommendations": [
    {"action": "Complete CKA certification", "impact": "high", "timeline": "6 weeks"}
  ]
}
```

### 6.9 Follow-Up Email Generation

**Trigger:** 7 days after applied_at with no response

**Output:**
```json
{
  "subject": "Follow-up: Senior Engineer Application — John Doe",
  "body": "Professional follow-up email under 150 words...",
  "tone": "professional"
}
```

Stored as notification payload so user can copy-paste and send.

### 6.10 Resume Tailoring

**Input:** Parsed resume + parsed JD

**Output:** Suggested changes for ATS optimization:
- tailored_summary (rewritten for this role)
- skills_to_highlight, skills_to_add
- bullet_rewrites (original → improved, with reason)
- keywords_to_include
- ats_improvements (specific tips)
- estimated_ats_score

---

## 7. Job Application Process

### 7.1 Information Submitted When Applying

| Field | Source |
|-------|--------|
| Full Name | users.full_name |
| Email | users.email |
| Phone | users.phone |
| Location | users.location |
| Work Authorization | users.work_authorization |
| Willing to Relocate | users.willing_to_relocate |
| Notice Period | users.notice_period_days |
| Expected Salary | users.expected_salary_min / max |
| Years of Experience | users.experience_years |
| Per-Skill Experience | users.tech_stack (JSONB) |
| LinkedIn URL | users.linkedin_url |
| GitHub URL | users.github_url |
| Portfolio URL | users.portfolio_url |
| Resume File | resumes.file_url (primary or selected) |
| Cover Letter | AI-generated (real data only) |
| Screening Answers | AI-drafted from profile or user-provided |

### 7.2 Answer Generation Pipeline

```
For each of 5 common screening questions:
  1. Check if user provided this answer (via prior needs_input round)
     → If yes: use user's answer verbatim (source: "user")

  2. Call answer_screening_question(question, user_profile, job)
     → AI checks user profile for required facts
     → If data present: generate truthful answer
     → If data missing: return "[NEEDS_INFO] what is needed"

  3. If [NEEDS_INFO] returned:
     → Add to answer_gaps list
     → Return {needs_input: answer_gaps} to frontend
     → User provides the answer manually
     → Re-call prepare with answer override

  4. All answers resolved → package is "ready"
```

Common screening questions pre-drafted:
1. "Why are you interested in this role?"
2. "What is your notice period / availability to start?"
3. "What are your salary expectations?"
4. "Are you authorized to work in this location?"
5. "Why are you a good fit for this position?"

### 7.3 Profile Data → Application Form Mapping

```
form_data snapshot:
  full_name           ← users.full_name
  email               ← users.email
  phone               ← users.phone
  location            ← users.location
  work_authorization  ← users.work_authorization
  willing_to_relocate ← users.willing_to_relocate
  notice_period_days  ← users.notice_period_days
  expected_salary_min ← users.expected_salary_min
  expected_salary_max ← users.expected_salary_max
  years_experience    ← users.experience_years
  skill_experience    ← users.tech_stack
  linkedin_url        ← users.linkedin_url
  github_url          ← users.github_url
  portfolio_url       ← users.portfolio_url
```

### 7.4 Pre-Submission Validation

Required fields that BLOCK submission if missing (never guessed or defaulted):

| Field | Label | Why Required |
|-------|-------|-------------|
| full_name | Full name | Application identity |
| email | Email | Communication channel |
| phone | Phone number | Required by most job boards |
| location | Current location | Relocation/remote eligibility |
| experience_years | Total years of experience | Baseline qualification |
| expected_salary_min | Expected salary | Required by most applications |
| work_authorization | Work authorization | Legal requirement |
| notice_period_days | Notice period | Start date planning |

Additional validation: per-skill years of experience required for skills the job asks for.

### 7.5 Submission Result Capture

On successful submission:
```sql
UPDATE job_applications SET
  status = 'applied',
  submission_status = 'submitted',
  submission_method = 'assisted' | 'auto',
  applied_via = 'assisted' | 'auto',
  applied_at = NOW(),
  application_id = 'external_confirmation_id',  -- if captured
  cover_letter = 'generated cover letter text',
  form_data = '{...snapshot...}',
  submitted_responses = '{"screening_answers": [...]}',
  job_snapshot = '{...job details at time of submission...}',
  resume_snapshot = '{...resume details...}'
WHERE id = application_id;
```

---

## 8. Backend Services

### 8.1 AI Service (`services/ai_service.py`)

**Purpose:** Central LLM integration layer — handles all AI-powered features.

**Responsibilities:**
- Provider management (Groq, NVIDIA, round-robin, failover)
- Job description parsing (batch and single)
- Match scoring (batch with double-evaluation)
- Cover letter generation
- Screening question answering (strict and permissive modes)
- Answer rephrasing
- Interview prep generation
- Skill gap analysis
- Follow-up email generation
- Resume tailoring suggestions

**APIs Called:**
- Groq: `https://api.groq.com/openai/v1/chat/completions`
- NVIDIA: `https://integrate.api.nvidia.com/v1/chat/completions`

**Inputs/Outputs:** See Section 6 for detailed prompts and response formats.

**Dependencies:** httpx, asyncio, config.settings

**Error Handling:**
- Rate limit (429): exponential backoff [2s, 4s, 8s] per job
- Provider failure: automatic failover to next available provider
- JSON parse failure: regex extraction with multiple fallback strategies
- Total failure: return empty defaults (never crashes the caller)

### 8.2 Application Service (`services/application_service.py`)

**Purpose:** Orchestrates the assisted-apply workflow and maintains the audit trail.

**Responsibilities:**
- Profile completeness validation (blocks on missing fields)
- Skill experience validation (blocks on missing per-skill years)
- Resume resolution (override → primary → most recent)
- Application package assembly
- Submission status tracking (not_started → ready → opened → submitted → failed)
- Audit trail logging (application_events)
- Graceful degradation when tracking columns are missing (pre-migration state)

**Key API:** `prepare_application(user_id, app_id, overrides)` — the central
entry point for building an application package.

**Dependencies:** ai_service (cover letter + screening answers), database

**Error Handling:**
- Missing profile fields: returns `{needs_input: [...]}` instead of guessing
- Missing screening answers: returns `{needs_input: [...]}` with AI-detected gaps
- Database column missing: falls back to legacy-only update
- All events logged whether or not tracking tables exist

### 8.3 Notification Service (`services/notification_service.py`)

**Purpose:** Delivers email and in-app notifications.

**Responsibilities:**
- Email delivery via Resend API
- In-app notification creation (notifications table)
- HTML email template rendering
- Event-specific templates (application submitted, new matches, follow-up, digest)

**Dependencies:** Resend API (RESEND_API_KEY), database

**Error Handling:** Email send failures are logged but don't crash the caller.

### 8.4 Job Discovery Worker (`workers/job_discovery.py`)

**Purpose:** Discovers new jobs from 21+ sources, scores them, and queues high-match jobs.

**Responsibilities:**
- Source selection based on region + user preferences + available API keys
- Concurrent scraping across multiple platforms
- Batch JD parsing and scoring via AI service
- Database upsert for new jobs and applications
- Auto-apply queue insertion for high-scoring jobs
- Notification creation for new matches

**Schedule:** Every 4 hours via Celery Beat, or on-demand via API.

**Dependencies:** All 21 scrapers, ai_service, database

### 8.5 Application Bot Worker (`workers/application_bot.py`)

**Purpose:** Submits applications via browser automation.

**Responsibilities:**
- Queue processing (apply_queue table)
- Resume download to temp file
- Cover letter generation
- Platform-specific browser automation (LinkedIn, Naukri, generic)
- Screening question answering via AI callback
- Result tracking (success/failure, confirmation ID)
- User notification on submission

**Schedule:** Every 30 minutes via Celery Beat, or on-demand via API.

**Dependencies:** Playwright, ai_service, notification_service, database

### 8.6 Notification Worker (`workers/notification_worker.py`)

**Purpose:** Sends scheduled notifications.

**Responsibilities:**
- Follow-up reminders: applications with no response after 7 days
- AI-generated follow-up email drafts stored as notifications
- Weekly pipeline digest: stats + top new matches

**Schedule:** Follow-ups daily at 9 AM, digest every Monday at 8 AM.

### 8.7 API Endpoints Reference

#### Jobs (`/api/v1/jobs`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | List jobs with filters |
| GET | `/{job_id}` | Get job details + match analysis |
| POST | `/{job_id}/score` | Trigger AI scoring for a job |
| POST | `/discover` | Trigger job discovery |

#### Applications (`/api/v1/applications`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | List applications (filterable) |
| GET | `/pipeline` | Kanban view grouped by status |
| GET | `/pending-approval` | Recommended tier awaiting approval |
| GET | `/{id}` | Get single application |
| PATCH | `/{id}` | Update status/notes/interview details |
| POST | `/{id}/star` | Toggle starred flag |
| POST | `/{id}/prepare` | Build assisted-apply package |
| POST | `/{id}/opened` | Record external page opened |
| POST | `/{id}/confirm-submit` | Confirm submission |
| POST | `/{id}/mark-failed` | Record failure |
| GET | `/{id}/events` | Get audit trail |
| POST | `/{id}/draft-answer` | AI draft screening answer |
| POST | `/{id}/rephrase-answer` | Polish screening answer |
| POST | `/{id}/draft-cover-letter` | Generate cover letter |
| POST | `/{id}/rephrase-cover-letter` | Polish cover letter |
| POST | `/{id}/apply` | Default apply action |
| GET | `/{id}/interview-prep` | Get/generate interview prep |
| GET | `/{id}/history` | Status change history |
| POST | `/{id}/approve` | Approve recommended job |
| POST | `/{id}/dismiss` | Dismiss recommended job |

#### Resumes (`/api/v1/resumes`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | List user's resumes |
| POST | `/upload` | Upload + AI parse |
| POST | `/{id}/set-primary` | Set as primary resume |
| DELETE | `/{id}` | Soft-delete |
| POST | `/{id}/tailor` | Generate tailored version for job |

#### AI (`/api/v1/ai`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/skill-gaps` | Skill gap analysis |
| POST | `/copilot` | Career question answering |
| POST | `/cover-letter` | Generate cover letter |

#### Copilot (`/api/v1/copilot`)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/chat` | Conversational career coach |
| POST | `/generate-cover-letter` | Cover letter for application |
| POST | `/analyze-resume` | AI resume analysis |
| GET | `/career-suggestions` | Growth recommendations |

#### Automation (`/api/v1/automation`)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/credentials` | Save job board credentials |
| GET | `/queue` | View apply queue status |
| DELETE | `/queue/{id}` | Cancel queued application |
| PATCH | `/settings` | Update automation settings |
| GET | `/blacklist` | Get blacklisted companies |
| POST | `/blacklist` | Add to blacklist |
| DELETE | `/blacklist/{name}` | Remove from blacklist |

#### Profile (`/api/v1/profile`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/application` | Get application profile |
| PUT | `/application` | Update application profile |
| GET | `/skill-experience` | Get per-skill years |
| PUT | `/skill-experience` | Update per-skill years |

#### Export (`/api/v1/export`)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/applications/csv` | Download as CSV |
| GET | `/applications/excel` | Download as styled Excel |

---

## 9. Frontend Features

### 9.1 Page Inventory

| Route | Page | Key Features |
|-------|------|-------------|
| `/` | Landing | 3D career universe (Three.js), hero section, CTA |
| `/auth/login` | Authentication | Google OAuth button, magic link option |
| `/dashboard` | Dashboard | Kanban pipeline, stats row, application cards |
| `/jobs` | Job Listings | Grid of job cards, filters (platform, work mode, salary, score) |
| `/applications` | Application Tracking | Table view, detail modal, apply/edit actions |
| `/resume` | Resume Management | Drag-drop upload, AI parsing results, version management |
| `/interview` | Interview Prep | Question cards, progress tracker, company research |
| `/analytics` | Analytics | Recharts: funnel, platform breakdown, timeline |
| `/settings` | Settings | Profile form, automation toggles, credential management |
| `/approve` | Approval Queue | Recommended tier jobs (60-79%) awaiting user decision |
| `/copilot` | Career Coach | Chat interface, context-aware AI conversation |

### 9.2 Dashboard

- **Pipeline Kanban:** 6 columns (Matched → Applied → In Progress → Interviews → Offers → Closed)
- **Application Cards:** Company name, job title, match score badge, status indicator
- **Stats Row:** Total applied, active interviews, offers, average match score
- **Data Source:** `GET /api/v1/applications/pipeline`

### 9.3 Job Listings

- **Job Cards:** Company logo, title, location, salary range, match score, work mode badge
- **Filters:** Platform, work mode, job type, salary range, minimum match score, skills
- **Sorting:** By match score, discovery date, salary
- **Actions:** View details, trigger scoring, start application
- **Data Source:** `GET /api/v1/jobs`

### 9.4 Application Detail

- **Overview:** Job info, match score, tier, status
- **Match Analysis:** Strengths, gaps, recommendations, score breakdown visualization
- **Cover Letter:** AI-generated with edit/regenerate/rephrase options
- **Screening Answers:** AI-drafted answers with edit/rephrase per question
- **Apply Workflow:** Prepare → Review → Open External → Confirm/Fail
- **Event Timeline:** Full audit trail of all workflow steps
- **Status History:** Every status transition with timestamps

### 9.5 Resume Page

- **Upload Zone:** React Dropzone for PDF/DOCX drag-and-drop
- **Parsing Results:** Structured display of extracted data (experience, education, skills, projects)
- **Version Management:** Multiple resumes with primary selection
- **ATS Score:** Estimated compatibility score

### 9.6 Interview Prep

- **Question Cards:** Technical, behavioral, system design, coding challenges
- **Ideal Answers:** Expandable answer sections with STAR format
- **Company Research:** Products, culture, recent news, questions to ask
- **Prep Plan:** Day-by-day preparation schedule (markdown rendered)
- **Salary Negotiation:** Target range, anchor strategy, talking points
- **Progress Tracker:** Completed / total questions, prep score

### 9.7 Analytics

- **Application Funnel:** Discovered → Matched → Applied → Interview → Offer
- **Platform Breakdown:** Bar chart of applications per source
- **Timeline:** Area chart of applications over time
- **Key Metrics:** Response rate, interview rate, offer rate, average match score

### 9.8 Settings

- **Profile Section:** Name, headline, location, contact, URLs, experience, salary
- **Preferences:** Work modes, job types, locations, open to remote
- **Skills:** Add/remove skills, per-skill years of experience
- **Automation:** Toggle auto-apply, set threshold, select preferred platforms
- **Credentials:** Save job board login credentials (LinkedIn, Naukri, etc.)
- **Company Blacklist:** Add/remove companies to exclude

### 9.9 Copilot (Career Coach)

- **Chat Interface:** Message input, conversation history
- **Contexts:** general, resume_review, cover_letter, interview, salary
- **User Context Injection:** Profile, skills, experience, recent applications
- **Markdown Rendering:** AI responses with formatting support
- **History Persistence:** Conversation stored in database

### 9.10 API Client (`lib/api.ts`)

Typed API client with Supabase auth token injection:

```typescript
// Auth: automatically extracts JWT from Supabase session
// Base URL: NEXT_PUBLIC_API_URL (default http://localhost:8000)
// Prefix: /api/v1

api.applications.list(params?)          // GET
api.applications.pipeline()             // GET
api.applications.prepare(id, overrides) // POST
api.applications.confirmSubmit(id)      // POST
api.applications.draftAnswer(id, q)     // POST
api.jobs.discover(data)                 // POST
api.resumes.upload(formData)            // POST (multipart)
api.copilot.chat(data)                  // POST
// ... 40+ typed API methods
```

---

## 10. Security & Data Protection

### 10.1 Authentication Flow

```
1. User clicks "Sign in with Google" on /auth/login
2. Supabase Auth redirects to Google OAuth consent screen
3. Google redirects back to /auth/callback with authorization code
4. Callback route exchanges code for Supabase session (JWT + refresh token)
5. Session stored in HTTP-only cookies via Supabase SSR helpers
6. Middleware checks session on every protected route request
7. Unauthenticated users redirected to /auth/login
8. Authenticated users redirected from /auth/login to /dashboard
```

### 10.2 Authorization Model

**Row Level Security (RLS):** Every table has RLS enabled. Users can only
access their own data.

```sql
-- Users: self only
CREATE POLICY "users_self" ON users FOR ALL USING (auth.uid() = id);

-- Resumes: own resumes only
CREATE POLICY "resumes_own" ON resumes FOR ALL USING (auth.uid() = user_id);

-- Job listings: read-only for authenticated users, write for service_role
CREATE POLICY "job_listings_read" ON job_listings FOR SELECT
  USING (auth.role() = 'authenticated');
CREATE POLICY "job_listings_insert_service" ON job_listings FOR INSERT
  WITH CHECK (auth.role() = 'service_role');

-- Applications, interview prep, credentials, notifications, queues,
-- analytics, blacklist: all scoped to auth.uid() = user_id
```

**Backend Access Tiers:**
- `get_supabase()` — Anon client, RLS enforced per user JWT
- `get_supabase_admin()` — Service role for workers (bypasses RLS)
- `get_authed_client(jwt)` — User-scoped client for specific operations

### 10.3 API Security

- **CORS:** Configured origins only (default: localhost:3000)
- **JWT Validation:** Every API call requires valid Supabase JWT in Authorization header
- **Input Validation:** Pydantic models validate all request bodies
- **SQL Injection:** Supabase client uses parameterized queries (no raw SQL)
- **Rate Limiting:** Per-platform rate limits for scrapers

### 10.4 Sensitive Data Handling

- **Credentials:** Job board passwords stored in `platform_credentials` table.
  Columns named `encrypted_username`/`encrypted_password` (schema comment:
  "use Supabase Vault in prod").
- **JWT Secret:** Stored in environment variable `SUPABASE_JWT_SECRET`
- **API Keys:** All LLM and service API keys stored in `.env`, never committed
- **Resume Files:** Stored in Supabase Storage with RLS-protected access

### 10.5 Anti-Fabrication Rules

A unique security feature: the AI service has strict anti-fabrication rules to
prevent the system from submitting false information on behalf of users:

1. Cover letters use ONLY facts from user profile and resume
2. Screening answers return `[NEEDS_INFO]` when data is missing
3. Rephrasing preserves meaning without adding new claims
4. Required profile fields are validated before any submission
5. Per-skill experience must be explicitly provided, never estimated

---

## 11. Monitoring & Logging

### 11.1 Application Logs

**Logger:** Loguru (structured Python logging)

**Log Points:**
- API request lifecycle (FastAPI)
- AI service calls (provider, tokens, latency)
- Scraper operations (source, query, results count, errors)
- Worker execution (discovery, auto-apply, notifications)
- Database operations (upserts, failures)

### 11.2 Auto-Apply Logs

Every auto-apply attempt is logged:
```
INFO  - Discovery for {user_id}: 8 sources → [remoteok, remotive, ...]
INFO  - Searching remoteok for 'Python React' in India
INFO  - Scraped 47 new jobs — starting parallel AI evaluation
INFO  - Double-evaluating 12 top matches for confidence scoring
INFO  - Batch scoring complete: 45/47 scored, 12 double-evaluated
INFO  - Discovery complete: 47 scraped, 45 evaluated, 23 matched (>=60%)
```

### 11.3 AI Request Logs

```
DEBUG - [Job 0] parsed via groq
DEBUG - [Job 5] groq 429 — backing off 2.0s
WARNING - [Job 5] groq failed: 429 Too Many Requests
INFO  - Falling back to nvidia
INFO  - Double-evaluating 8 top matches for confidence scoring
```

### 11.4 Audit Trail

**application_events table:** Every workflow step recorded with:
- event_type (prepared, cover_letter_generated, opened_external, submitted, failed)
- message (human-readable description)
- metadata (JSONB with context-specific data)
- created_at (timestamp)

**application_status_history table:** Every status transition recorded via database trigger:
- old_status, new_status, changed_by, note, metadata, changed_at

### 11.5 Error Tracking

Errors are captured at multiple levels:
- API layer: HTTPException with status codes and detail messages
- Service layer: try/except with logger.error() and graceful fallbacks
- Worker layer: Celery task failure logging + apply_queue.error_msg
- Database layer: Constraint violations caught and handled

---

## 12. Current Limitations & Technical Debt

### 12.1 Known Issues

1. **Credential Encryption:** Platform credentials are stored with `encrypted_`
   column names but may not use actual encryption in the current implementation.
   The schema comment says "use Supabase Vault in prod."

2. **Playwright Scraper Fragility:** Browser-based scrapers (LinkedIn, Naukri,
   etc.) are inherently fragile — they break when job board UIs change. CSS
   selectors and page flows require ongoing maintenance.

3. **Generic Portal Apply:** The generic portal scraper (`_apply_generic_portal`)
   uses simple CSS selector heuristics to detect form fields. It works for basic
   forms but fails on complex multi-step applications, CAPTCHAs, or SPAs.

4. **Stuck Applications Recovery:** Migration 03 includes a one-time fix for
   applications stuck in "applying" status from the old bot. Future stuck states
   need a scheduled cleanup job.

5. **Pre-Migration Compatibility:** The application service has dual-path logic
   to handle databases that haven't run migration 03 yet. This adds complexity.

### 12.2 Missing Features

1. **Real-time Notifications:** No WebSocket/SSE — notifications require page refresh.
2. **Multi-Language Support:** UI is English-only.
3. **Resume Version Diff:** No visual diff between resume versions.
4. **Application Analytics:** analytics_snapshots table exists but no automated
   snapshot creation (needs a Celery Beat task).
5. **OAuth for Job Boards:** Only username/password auth for job boards;
   no OAuth flow for LinkedIn/Naukri.
6. **Confirmation Screenshots:** The `confirmation_screenshot_url` column
   exists but screenshot capture is not implemented in the current bot.

### 12.3 Scalability Concerns

1. **Free-Tier LLM Limits:** Groq (~30 RPM) and NVIDIA (~20 RPM) free tiers
   limit throughput. At scale, paid API access is required.
2. **Playwright Browser Instances:** Each scraper launches a headless Chromium.
   Concurrent discovery runs for many users will exhaust memory.
3. **Single Celery Worker:** Current Docker setup runs one worker process.
   Production needs multiple workers with queue-specific routing.
4. **Database Connections:** Supabase has connection limits per plan.
   Workers using admin client may exhaust the pool under load.

### 12.4 Reliability Concerns

1. **No Health Check for Workers:** Docker health checks exist only for the API
   server, not for Celery workers or Beat scheduler.
2. **No Dead Letter Queue:** Failed apply_queue items after max_attempts are
   marked "failed" but not moved to a DLQ for investigation.
3. **No Idempotency Keys:** API endpoints don't use idempotency keys —
   duplicate requests could create duplicate side effects.
4. **Embedding Staleness:** User and job embeddings are not automatically
   refreshed when profiles or job listings are updated.

---

## 13. Improvement Roadmap

### Priority 1: Critical Fixes

| Item | Impact | Effort |
|------|--------|--------|
| Implement real credential encryption (Supabase Vault or pgcrypto) | Security | Medium |
| Add worker health checks to Docker Compose | Reliability | Low |
| Add idempotency keys to apply and submission endpoints | Reliability | Medium |
| Automated cleanup of stuck "applying" applications | Reliability | Low |

### Priority 2: High-Priority Improvements

| Item | Impact | Effort |
|------|--------|--------|
| WebSocket/SSE for real-time notifications | UX | Medium |
| Analytics snapshot generation (Celery Beat task) | Feature | Low |
| Confirmation screenshot capture during auto-apply | Verification | Medium |
| Dead letter queue for permanently failed applications | Observability | Low |
| Embedding refresh on profile/job update | AI Quality | Medium |

### Priority 3: Medium-Priority Enhancements

| Item | Impact | Effort |
|------|--------|--------|
| OAuth integration for LinkedIn/Naukri (replace password auth) | Security/UX | High |
| Resume version diff viewer | UX | Medium |
| Multi-language support (i18n) | Accessibility | High |
| Horizontal scaling: multi-worker Celery with Redis Sentinel | Scale | High |
| Structured logging with correlation IDs across services | Observability | Medium |

### Priority 4: Future Features

| Item | Impact | Effort |
|------|--------|--------|
| Mobile app (React Native) | Reach | Very High |
| Salary negotiation simulator (AI-powered) | Feature | Medium |
| Company research aggregation (Glassdoor reviews, LinkedIn data) | Feature | High |
| Application success prediction model (ML) | AI | High |
| Browser extension for one-click apply on any job page | UX | High |
| Team/recruiter portal for B2B use cases | Business | Very High |

---

## 14. Flow Diagrams

### 14.1 User Onboarding

```
┌─────────┐     ┌──────────────┐     ┌──────────────┐
│ Landing  │────▶│ Google OAuth  │────▶│ OAuth        │
│ Page (/) │     │ /auth/login   │     │ Callback     │
└─────────┘     └──────────────┘     └──────┬───────┘
                                            │ Session created
                                            ▼
                                     ┌──────────────┐
                                     │ Middleware    │
                                     │ checks       │
                                     │ is_onboarded │
                                     └──────┬───────┘
                                            │ false
                                            ▼
                                     ┌──────────────┐
                                     │ /settings    │
                                     │ Profile form │
                                     └──────┬───────┘
                                            │ Save profile
                                            ▼
                                     ┌──────────────┐
                                     │ /resume      │
                                     │ Upload resume│
                                     └──────┬───────┘
                                            │ AI parses + syncs skills
                                            ▼
                                     ┌──────────────┐
                                     │ /dashboard   │
                                     │ Ready to use │
                                     └──────────────┘
```

### 14.2 Resume Processing

```
┌──────────┐     ┌──────────────┐     ┌──────────────────────┐
│ User     │     │ POST         │     │ Backend              │
│ drops    │────▶│ /resumes/    │────▶│ 1. Validate file     │
│ PDF/DOCX │     │ upload       │     │ 2. Extract raw text  │
└──────────┘     └──────────────┘     │    (PyPDF2/docx)     │
                                      │ 3. Upload to Storage │
                                      │ 4. Send to LLM      │
                                      └──────────┬───────────┘
                                                 │
                                                 ▼
                                      ┌──────────────────────┐
                                      │ LLM extracts:        │
                                      │ - Experience[]       │
                                      │ - Education[]        │
                                      │ - Skills[]           │
                                      │ - Tech stack{}       │
                                      │ - Projects[]         │
                                      │ - Certifications[]   │
                                      └──────────┬───────────┘
                                                 │
                                                 ▼
                                      ┌──────────────────────┐
                                      │ Backend:             │
                                      │ 5. Store parsed_data │
                                      │ 6. Compute ATS score │
                                      │ 7. Sync skills →     │
                                      │    user profile      │
                                      │ 8. Set as primary    │
                                      └──────────────────────┘
```

### 14.3 Job Discovery

```
┌───────────┐
│ Trigger:  │
│ Celery    │──── Every 4 hours (or manual /jobs/discover)
│ Beat      │
└─────┬─────┘
      ▼
┌─────────────────────────┐
│ Load User Profile       │
│ - skills, headline      │
│ - career_goals          │
│ - preferred_platforms   │
│ - preferred_locations   │
│ - company_blacklist     │
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│ Build Search Queries    │
│ (up to 3 from profile)  │
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│ Select Sources          │
│ API-first (always on)   │◀─── remoteok, remotive, arbeitnow, themuse
│ Keyed APIs (if key set) │◀─── adzuna, jooble, jsearch
│ Playwright (if opted in)│◀─── linkedin, naukri, indeed, ...
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│ Scrape Concurrently     │
│ Per source, per query   │
│ Rate-limited per source │
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│ Filter Results          │
│ - Dedup by source_url   │
│ - Skip blacklisted cos  │
│ - Skip already-seen     │
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│ Batch Parse JDs         │ ◀── Groq + NVIDIA (round-robin)
│ (async, 4 concurrent)   │
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│ Store in job_listings   │
│ (upsert by source_url)  │
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│ Batch Score Jobs        │ ◀── Dual-LLM with double-eval >= 70
│ (async, 4 concurrent)   │
└─────────┬───────────────┘
          ▼
┌─────────────────────────┐
│ Assign Tiers + Store    │
│ auto_apply >= 80        │──▶ Queue for auto-apply
│ recommended 60-79       │──▶ Show on /approve page
│ watchlist 50-59         │──▶ Show on /jobs page
│ archived < 50           │──▶ Hidden
└─────────────────────────┘
```

### 14.4 Job Scoring

```
┌────────────────────────────────────────────────────┐
│                Phase 1: Distributed Scoring         │
│                                                     │
│  Job 0 ──▶ Groq  ──▶ Score: 85                    │
│  Job 1 ──▶ NVIDIA ──▶ Score: 62                    │
│  Job 2 ──▶ Groq  ──▶ Score: 45                    │
│  Job 3 ──▶ NVIDIA ──▶ Score: 73                    │
│  Job 4 ──▶ Groq  ──▶ Score: 91                    │
│  Job 5 ──▶ NVIDIA ──▶ Score: 38                    │
│                                                     │
│  (Round-robin, rate-limit aware, failover on error) │
└────────────────────────┬───────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────┐
│          Phase 2: Double Evaluation (>= 70)         │
│                                                     │
│  Job 0 (85 by Groq)  ──▶ NVIDIA ──▶ 82            │
│    → Final: avg(85,82) = 84, spread: 3             │
│                                                     │
│  Job 3 (73 by NVIDIA) ──▶ Groq  ──▶ 78            │
│    → Final: avg(73,78) = 76, spread: 5             │
│                                                     │
│  Job 4 (91 by Groq)  ──▶ NVIDIA ──▶ 88            │
│    → Final: avg(91,88) = 90, spread: 3             │
│                                                     │
│  (Strengths/gaps merged, tiers re-evaluated)        │
└────────────────────────────────────────────────────┘
```

### 14.5 Auto-Apply Workflow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐
│ apply_queue  │     │ Celery Beat  │     │ Application Bot      │
│ table        │◀────│ every 30 min │────▶│ Worker               │
│ status=      │     └──────────────┘     └──────────┬───────────┘
│  "pending"   │                                     │
└──────────────┘                                     ▼
                                          ┌──────────────────────┐
                                          │ 1. Load queue item   │
                                          │ 2. Mark "running"    │
                                          │ 3. Load app details  │
                                          │ 4. Load user profile │
                                          │ 5. Load credentials  │
                                          │ 6. Download resume   │
                                          │ 7. Generate cover    │
                                          │    letter (AI)       │
                                          └──────────┬───────────┘
                                                     │
                                    ┌────────────────┼────────────────┐
                                    ▼                ▼                ▼
                             ┌───────────┐  ┌────────────┐  ┌──────────────┐
                             │ LinkedIn  │  │ Naukri     │  │ Generic      │
                             │ Easy Apply│  │ Apply      │  │ Portal       │
                             │           │  │            │  │              │
                             │ Login     │  │ Login      │  │ Open URL     │
                             │ Navigate  │  │ Navigate   │  │ Detect form  │
                             │ Fill form │  │ Click apply│  │ Fill fields  │
                             │ Upload CV │  │            │  │ Upload CV    │
                             │ Answer Qs │  │            │  │ Submit       │
                             │ Submit    │  │            │  │              │
                             └─────┬─────┘  └─────┬──────┘  └──────┬───────┘
                                   │              │                │
                                   └──────────────┼────────────────┘
                                                  ▼
                                   ┌──────────────────────────────┐
                                   │         Result?               │
                                   └──────────┬───────────────────┘
                                    ┌─────────┴─────────┐
                              SUCCESS                 FAILURE
                                    ▼                     ▼
                             ┌─────────────┐     ┌──────────────────┐
                             │ status =    │     │ Revert status    │
                             │ "applied"   │     │ to "matched"     │
                             │ applied_at  │     │                  │
                             │ = now()     │     │ attempts < max?  │
                             │ notify user │     │ Yes → re-queue   │
                             └─────────────┘     │ No → mark failed │
                                                 └──────────────────┘
```

### 14.6 Application Tracking Flow

```
┌──────────┐     ┌──────────┐     ┌──────────────┐     ┌────────────┐
│ Discovery│────▶│ Scoring  │────▶│ Tier Assign  │────▶│ Database   │
│ Worker   │     │ (AI)     │     │ auto/rec/    │     │ Records    │
└──────────┘     └──────────┘     │ watch/archive│     │ Created    │
                                  └──────────────┘     └──────┬─────┘
                                                              │
                    ┌─────────────────────────────────────────┘
                    ▼
             ┌──────────────────────────────────────────────────┐
             │              STATUS TRANSITIONS                   │
             │                                                   │
             │  Each transition logged to:                       │
             │  • application_status_history (via DB trigger)    │
             │  • application_events (via service log_event)     │
             │                                                   │
             │  matched ──▶ queued ──▶ applying ──▶ applied     │
             │                                      │            │
             │                              under_review         │
             │                                      │            │
             │                              assessment           │
             │                                      │            │
             │                           interview_scheduled     │
             │                              │          │         │
             │                     technical_round  hr_round     │
             │                              │          │         │
             │                           offer_received          │
             │                              │          │         │
             │                           accepted   withdrawn    │
             └──────────────────────────────────────────────────┘
```

### 14.7 AI Answer Generation

```
┌──────────────┐
│ Screening    │
│ Question     │
│ received     │
└──────┬───────┘
       ▼
┌──────────────────────────────┐
│ Load Context:                │
│ - User profile (all fields)  │
│ - Resume parsed_data.summary │
│ - Job details (title, co,    │
│   skills, JD)                │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ Build Prompt:                │
│ - CANDIDATE DATA block       │
│   (missing values shown as   │
│    "(not provided)")         │
│ - QUESTION + JOB context     │
│ - Anti-fabrication rules     │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ Call LLM (Groq preferred)    │
│ temperature=0.6, top_p=0.95  │
│ max_tokens=800               │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ Response contains            │
│ [NEEDS_INFO]?                │
│                              │
│ YES → Return to user:        │
│   "This question requires    │
│    your input: {what}"       │
│                              │
│ NO → Extract clean answer    │
│   via _extract_answer()      │
│   pipeline                   │
└──────────────────────────────┘
```

### 14.8 AI Answer Optimization (Rephrasing)

```
┌──────────────┐
│ User's draft │
│ answer       │
└──────┬───────┘
       ▼
┌──────────────────────────────┐
│ Build Prompt:                │
│ - QUESTION                   │
│ - CANDIDATE'S DRAFT          │
│ - CONTEXT (role, company)    │
│                              │
│ Rules:                       │
│ - Improve clarity/grammar    │
│ - Preserve meaning/intent    │
│ - Do NOT add new facts       │
│ - Do NOT remove specifics    │
│ - Keep ±25% length           │
│ - Stay first person          │
│                              │
│ Output: <ANSWER>polished     │
│ text</ANSWER>                │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ Call LLM (Groq preferred)    │
└──────────────┬───────────────┘
               ▼
┌──────────────────────────────┐
│ _extract_answer() pipeline:  │
│ 1. Find <ANSWER> tags        │
│ 2. Strip <think> blocks      │
│ 3. Check for markers         │
│ 4. Find quoted blocks        │
│ 5. Clean and return          │
└──────────────────────────────┘
```

---

## Appendix A: Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `SUPABASE_URL` | Yes | — | Supabase project URL |
| `SUPABASE_ANON_KEY` | Yes | — | Supabase anonymous key |
| `SUPABASE_SERVICE_ROLE_KEY` | Yes | — | Supabase service role key |
| `SUPABASE_JWT_SECRET` | Yes | — | JWT signing secret |
| `NEXT_PUBLIC_SUPABASE_URL` | Yes | — | Frontend Supabase URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Yes | — | Frontend anonymous key |
| `NEXT_PUBLIC_API_URL` | No | `http://localhost:8000` | Backend API URL |
| `GROQ_API_KEY` | No* | — | Groq API key (* at least one LLM key required) |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq model ID |
| `NVIDIA_API_KEY` | No* | — | NVIDIA NIM API key |
| `NVIDIA_MODEL` | No | `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` | NVIDIA model |
| `OPENAI_API_KEY` | No | — | For embeddings (text-embedding-3-small) |
| `ADZUNA_APP_ID` | No | — | Adzuna API app ID |
| `ADZUNA_APP_KEY` | No | — | Adzuna API key |
| `JOOBLE_API_KEY` | No | — | Jooble API key |
| `JSEARCH_RAPIDAPI_KEY` | No | — | JSearch RapidAPI key |
| `REDIS_URL` | No | `redis://localhost:6379/0` | Redis connection URL |
| `RESEND_API_KEY` | No | — | Resend email API key |
| `AUTO_APPLY_THRESHOLD` | No | `80` | Score threshold for auto-apply |
| `RECOMMENDED_THRESHOLD` | No | `60` | Score threshold for recommended |
| `WATCHLIST_THRESHOLD` | No | `50` | Score threshold for watchlist |
| `MAX_JOBS_PER_DISCOVERY` | No | `50` | Max jobs fetched per discovery run |
| `PLAYWRIGHT_HEADLESS` | No | `true` | Run browsers headless |
| `ALLOWED_ORIGINS` | No | `http://localhost:3000` | CORS allowed origins |

## Appendix B: Docker Compose Services

| Service | Image | Port | Command | Purpose |
|---------|-------|------|---------|---------|
| `redis` | redis:7-alpine | 6379 | Default | Message broker + cache |
| `api` | Custom Python 3.11 | 8000 | `uvicorn main:app` | FastAPI backend |
| `worker` | Custom Python 3.11 | — | `celery worker` | Background job processor |
| `beat` | Custom Python 3.11 | — | `celery beat` | Scheduled task scheduler |
| `web` | node:20-alpine | 3000 | `npm run dev` | Next.js frontend |

## Appendix C: File Structure

```
job-platform/
├── .env                          # Environment configuration
├── .env.example                  # Template with all variables
├── docker-compose.yml            # Full stack orchestration
├── PROJECT_DOCUMENTATION.md      # This file
│
├── database/
│   ├── schema.sql                # Complete PostgreSQL schema (16 tables, 7 enums)
│   ├── rls_policies.sql          # Row Level Security policies (11 tables)
│   ├── 02_api_sources.sql        # Migration: add API-first platform enums
│   └── 03_application_tracking.sql # Migration: assisted-apply audit trail
│
├── apps/api/                     # Python FastAPI Backend
│   ├── main.py                   # App entry point + route registration
│   ├── config.py                 # Pydantic Settings (environment variables)
│   ├── auth.py                   # JWT validation (Supabase)
│   ├── database.py               # Supabase client factory
│   ├── requirements.txt          # Python dependencies
│   ├── Dockerfile                # API container image
│   ├── Dockerfile.worker         # Worker container image
│   │
│   ├── models/
│   │   ├── job.py                # Job-related Pydantic schemas
│   │   ├── application.py        # Application schemas + enums
│   │   └── resume.py             # Resume schemas (parsed data structure)
│   │
│   ├── routers/
│   │   ├── jobs.py               # Job discovery + browsing endpoints
│   │   ├── applications.py       # Application lifecycle + assisted apply
│   │   ├── resumes.py            # Resume upload + AI parsing + tailoring
│   │   ├── ai.py                 # Skill gaps, copilot, cover letters
│   │   ├── automation.py         # Credentials, queue, blacklist, settings
│   │   ├── copilot.py            # Career coaching AI chat
│   │   ├── export.py             # CSV/Excel export
│   │   └── profile.py            # Application profile + skill experience
│   │
│   ├── services/
│   │   ├── ai_service.py         # Dual-LLM engine (scoring, generation, parsing)
│   │   ├── application_service.py # Assisted-apply orchestration + audit trail
│   │   ├── notification_service.py # Email + in-app notification delivery
│   │   └── email_service.py      # Resend API integration
│   │
│   ├── workers/
│   │   ├── celery_app.py         # Celery config + Beat schedule
│   │   ├── job_discovery.py      # Source registry + discovery pipeline
│   │   ├── application_bot.py    # Browser automation for auto-apply
│   │   └── notification_worker.py # Follow-up reminders + weekly digest
│   │
│   └── scrapers/
│       ├── base.py               # BaseScraper + RateLimiter
│       ├── api_base.py           # API scraper base class
│       ├── linkedin.py           # LinkedIn (Playwright + login)
│       ├── naukri.py             # Naukri (Playwright + login)
│       ├── indeed.py             # Indeed (Playwright)
│       ├── wellfound.py          # Wellfound (Playwright)
│       ├── glassdoor.py          # Glassdoor (Playwright)
│       ├── hirist.py             # Hirist (Playwright)
│       ├── instahyre.py          # Instahyre (Playwright)
│       ├── cutshort.py           # Cutshort (Playwright)
│       ├── foundit.py            # Foundit (Playwright)
│       ├── dice.py               # Dice (Playwright)
│       ├── ziprecruiter.py       # ZipRecruiter (Playwright)
│       ├── weworkremotely.py     # WeWorkRemotely (Playwright)
│       ├── remoteok.py           # RemoteOK (API, keyless)
│       ├── remotive.py           # Remotive (API, keyless)
│       ├── arbeitnow.py          # Arbeitnow (API, keyless)
│       ├── themuse.py            # TheMuse (API, keyless)
│       ├── adzuna.py             # Adzuna (API, keyed)
│       ├── jooble.py             # Jooble (API, keyed)
│       └── jsearch.py            # JSearch (API, keyed)
│
└── apps/web/                     # Next.js 14 Frontend
    ├── src/
    │   ├── app/                  # App Router pages
    │   │   ├── page.tsx          # Landing page (/)
    │   │   ├── layout.tsx        # Root layout
    │   │   ├── auth/login/page.tsx    # Login page
    │   │   ├── auth/callback/route.ts # OAuth callback
    │   │   ├── dashboard/page.tsx     # Kanban dashboard
    │   │   ├── jobs/page.tsx          # Job listings grid
    │   │   ├── applications/page.tsx  # Applications table
    │   │   ├── resume/page.tsx        # Resume management
    │   │   ├── interview/page.tsx     # Interview prep
    │   │   ├── analytics/page.tsx     # Analytics charts
    │   │   ├── settings/page.tsx      # Profile + automation settings
    │   │   ├── approve/page.tsx       # Approval queue
    │   │   └── copilot/page.tsx       # Career coach AI chat
    │   │
    │   ├── components/           # React components
    │   │   ├── landing/          # Landing page (3D scene, hero)
    │   │   ├── dashboard/        # Kanban, cards, stats
    │   │   ├── applications/     # Application table + modal
    │   │   ├── jobs/             # Job grid + cards
    │   │   ├── resume/           # Upload + parsing UI
    │   │   ├── interview/        # Question cards + prep
    │   │   ├── analytics/        # Recharts visualizations
    │   │   ├── settings/         # Profile form + toggles
    │   │   ├── copilot/          # Chat interface
    │   │   ├── approve/          # Approval queue UI
    │   │   ├── layout/           # Sidebar navigation
    │   │   └── ui/               # Primitive components
    │   │
    │   ├── lib/
    │   │   ├── api.ts            # Typed API client (40+ methods)
    │   │   ├── supabase/client.ts # Browser Supabase client
    │   │   ├── supabase/server.ts # Server Supabase client
    │   │   └── utils.ts          # Helpers (cn, formatting)
    │   │
    │   ├── types/index.ts        # TypeScript interfaces + enums
    │   └── globals.css           # Tailwind directives
    │
    ├── middleware.ts              # Auth middleware (route protection)
    ├── package.json              # Node dependencies
    ├── tailwind.config.ts        # Tailwind configuration
    ├── tsconfig.json             # TypeScript configuration
    └── Dockerfile                # Frontend container image
```

---

*Generated for the JobPlatform AI project. Last updated: June 2026.*
