-- ============================================================
-- PENDING MIGRATIONS BUNDLE — generated 2026-07-04
-- Your database was missing migrations 03, 05 (x2), 06, 10.
-- (08_answer_bank.sql is already applied.) All statements are
-- idempotent — safe to run once, top to bottom, in one go.
-- ============================================================

-- ──────────────────────────────────────────────────────────
-- >>> 03_application_tracking.sql
-- ──────────────────────────────────────────────────────────
-- ============================================================
-- Migration 03 — Application Tracking & Assisted-Apply audit trail
-- Run once in the Supabase SQL editor. Idempotent.
-- ============================================================

-- ── Application Profile fields (reusable, on users) ──
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS work_authorization TEXT,
  ADD COLUMN IF NOT EXISTS willing_to_relocate BOOLEAN DEFAULT TRUE;

-- ── Submission tracking on job_applications ──
-- These flow into the application_details view automatically (it selects a.*).
ALTER TABLE public.job_applications
  ADD COLUMN IF NOT EXISTS submission_status TEXT DEFAULT 'not_started',
    -- not_started | ready | opened | submitted | failed
  ADD COLUMN IF NOT EXISTS submission_method TEXT,
    -- assisted | auto | manual
  ADD COLUMN IF NOT EXISTS form_data JSONB DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS submitted_responses JSONB DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS job_snapshot JSONB DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS resume_snapshot JSONB DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS failure_reason TEXT,
  ADD COLUMN IF NOT EXISTS prepared_at TIMESTAMPTZ;

-- ── Audit trail / workflow event log ──
CREATE TABLE IF NOT EXISTS public.application_events (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  application_id UUID NOT NULL REFERENCES public.job_applications(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  event_type TEXT NOT NULL,
    -- prepared | resume_selected | cover_letter_generated | answers_drafted
    -- | opened_external | submitted | failed | status_changed | user_confirmed | note
  message TEXT,
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_application_events_app
  ON public.application_events(application_id, created_at DESC);

ALTER TABLE public.application_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "application_events_own" ON public.application_events;
CREATE POLICY "application_events_own" ON public.application_events
  FOR ALL USING (auth.uid() = user_id);

-- ── Recover stuck applications ──
-- Rows left in 'applying' by the old (failing) bot, never actually submitted.
UPDATE public.job_applications
SET status = 'matched', submission_status = 'not_started'
WHERE status = 'applying' AND applied_at IS NULL;

-- ──────────────────────────────────────────────────────────
-- >>> 05_recency_relevance.sql
-- ──────────────────────────────────────────────────────────
-- Migration: Add posted_at for recency sorting + extend application_details view
-- Run this in Supabase SQL Editor after schema.sql

-- 1. Add posted_at column to job_listings
ALTER TABLE public.job_listings
  ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ;

-- 2. Index for recency ordering
CREATE INDEX IF NOT EXISTS idx_job_listings_posted
  ON public.job_listings(posted_at DESC NULLS LAST);

-- 3. Backfill existing rows from discovered_at
UPDATE public.job_listings
  SET posted_at = discovered_at
  WHERE posted_at IS NULL;

-- 4. Extend the view to expose posted_at + discovered_at
DROP VIEW IF EXISTS public.application_details;
CREATE OR REPLACE VIEW public.application_details AS
SELECT
  a.*,
  j.title AS job_title, j.company AS job_company,
  j.company_logo_url, j.location AS job_location,
  j.work_mode AS job_work_mode, j.job_type,
  j.salary_min, j.salary_max, j.salary_currency,
  j.source_platform, j.source_url, j.apply_url,
  j.is_easy_apply, j.required_skills AS job_required_skills, j.jd_text,
  j.posted_at AS job_posted_at,
  j.discovered_at AS job_discovered_at,
  r.name AS resume_name, r.file_url AS resume_url
FROM public.job_applications a
JOIN public.job_listings j ON a.job_listing_id = j.id
LEFT JOIN public.resumes r ON a.resume_id = r.id;

-- ──────────────────────────────────────────────────────────
-- >>> 05_rate_limiting.sql
-- ──────────────────────────────────────────────────────────
-- ============================================================
-- Migration 05: Rate Limiting & Application Deduplication
-- ============================================================
-- Adds:
-- 1. applied_url column to job_applications (for redirect-to-applied-job)
-- 2. Index for fast daily application count queries (rate limiting)
-- 3. Index for duplicate detection by source_url
-- ============================================================

-- Store the platform-specific URL of the submitted application
-- (e.g., the LinkedIn Easy Apply job page after submission)
ALTER TABLE public.job_applications
  ADD COLUMN IF NOT EXISTS applied_url TEXT;

COMMENT ON COLUMN public.job_applications.applied_url IS
  'URL of the submitted application on the platform — used to redirect user to already-applied jobs';

-- Fast lookup for rate limiting: count today's auto-applied jobs per user
CREATE INDEX IF NOT EXISTS idx_applications_daily_rate
  ON public.job_applications(user_id, applied_at DESC)
  WHERE status = 'applied' AND applied_via = 'auto';

-- Fast duplicate detection: find if user already applied to a specific job listing
CREATE INDEX IF NOT EXISTS idx_applications_dedup
  ON public.job_applications(user_id, job_listing_id)
  WHERE status = 'applied';

-- Update the application_details view to include applied_url
DROP VIEW IF EXISTS public.application_details;
CREATE OR REPLACE VIEW public.application_details AS
SELECT
  a.*,
  j.title AS job_title, j.company AS job_company,
  j.company_logo_url, j.location AS job_location,
  j.work_mode AS job_work_mode, j.job_type,
  j.salary_min, j.salary_max, j.salary_currency,
  j.source_platform, j.source_url, j.apply_url,
  j.is_easy_apply, j.required_skills AS job_required_skills, j.jd_text,
  r.name AS resume_name, r.file_url AS resume_url
FROM public.job_applications a
JOIN public.job_listings j ON a.job_listing_id = j.id
LEFT JOIN public.resumes r ON a.resume_id = r.id;

-- ──────────────────────────────────────────────────────────
-- >>> 06_listing_validation.sql
-- ──────────────────────────────────────────────────────────
-- ============================================================
-- Migration 06 — Stale-listing validation
-- Marks dead/expired job listings inactive and exposes that state
-- through the application_details view. Idempotent.
-- ============================================================

-- ── Expiry tracking on job_listings ──
ALTER TABLE public.job_listings
  ADD COLUMN IF NOT EXISTS expired_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS expiry_reason TEXT,
  ADD COLUMN IF NOT EXISTS last_validated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_job_listings_revalidate
  ON public.job_listings(is_active, last_validated_at NULLS FIRST);

-- ── Expose listing liveness + posting timestamps through the view ──
-- Rebuilt to add job_is_active / job_expired_at while preserving the
-- columns added in migration 05 (posted_at, discovered_at).
DROP VIEW IF EXISTS public.application_details;
CREATE OR REPLACE VIEW public.application_details AS
SELECT
  a.*,
  j.title AS job_title, j.company AS job_company,
  j.company_logo_url, j.location AS job_location,
  j.work_mode AS job_work_mode, j.job_type,
  j.salary_min, j.salary_max, j.salary_currency,
  j.source_platform, j.source_url, j.apply_url,
  j.is_easy_apply, j.required_skills AS job_required_skills, j.jd_text,
  j.posted_at AS job_posted_at,
  j.discovered_at AS job_discovered_at,
  j.is_active AS job_is_active,
  j.expired_at AS job_expired_at,
  j.expiry_reason AS job_expiry_reason,
  r.name AS resume_name, r.file_url AS resume_url
FROM public.job_applications a
JOIN public.job_listings j ON a.job_listing_id = j.id
LEFT JOIN public.resumes r ON a.resume_id = r.id;

-- ──────────────────────────────────────────────────────────
-- >>> 10_manual_apply.sql
-- ──────────────────────────────────────────────────────────
-- ============================================================
-- Migration 10 — Manual Apply lane
-- When the bot cannot submit an application (no automation adapter,
-- exhausted retries), the application moves to 'manual_apply' instead
-- of silently reappearing in the approval queue. The user completes
-- it from the Approve Jobs → Manual Apply section. Idempotent.
-- ============================================================

ALTER TYPE application_status ADD VALUE IF NOT EXISTS 'manual_apply';

-- ──────────────────────────────────────────────────────────
-- >>> 09_new_sources.sql  (+ all API/Phase-3 source platforms)
-- ──────────────────────────────────────────────────────────
-- Without these, listings from newer boards (TimesJobs, Shine, iimjobs,
-- Freshersworld, and the API sources) fall back to source_platform='other'
-- and cannot be filtered by their real source. Idempotent.
-- Note: ADD VALUE cannot be used in the SAME transaction that adds it, so run
-- this bundle top-to-bottom as separate statements (the Supabase SQL editor
-- does this by default) rather than wrapping it in BEGIN/COMMIT.
-- ============================================================
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'iimjobs';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'timesjobs';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'shine';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'freshersworld';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'ycombinator';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'remotive';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'arbeitnow';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'themuse';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'adzuna';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'jooble';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'jsearch';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'careerjet';

-- ──────────────────────────────────────────────────────────
-- >>> 12_hr_contact.sql
-- ──────────────────────────────────────────────────────────
-- Adds a hiring contact (email / LinkedIn) per listing and exposes it through
-- the view. hr_email / hr_linkedin_url are verified-only (provider-sourced);
-- hr_linkedin_search_url is a keyless people-search link. Idempotent.
ALTER TABLE public.job_listings
  ADD COLUMN IF NOT EXISTS hr_name TEXT,
  ADD COLUMN IF NOT EXISTS hr_email TEXT,
  ADD COLUMN IF NOT EXISTS hr_linkedin_url TEXT,
  ADD COLUMN IF NOT EXISTS hr_linkedin_search_url TEXT,
  ADD COLUMN IF NOT EXISTS hr_contact_source TEXT,
  ADD COLUMN IF NOT EXISTS hr_contact_confidence SMALLINT;

DROP VIEW IF EXISTS public.application_details;
CREATE OR REPLACE VIEW public.application_details AS
SELECT
  a.*,
  j.title AS job_title, j.company AS job_company,
  j.company_logo_url, j.location AS job_location,
  j.work_mode AS job_work_mode, j.job_type,
  j.salary_min, j.salary_max, j.salary_currency,
  j.source_platform, j.source_url, j.apply_url,
  j.is_easy_apply, j.required_skills AS job_required_skills, j.jd_text,
  j.posted_at AS job_posted_at,
  j.discovered_at AS job_discovered_at,
  j.is_active AS job_is_active,
  j.expired_at AS job_expired_at,
  j.expiry_reason AS job_expiry_reason,
  j.hr_name, j.hr_email, j.hr_linkedin_url,
  j.hr_linkedin_search_url, j.hr_contact_source, j.hr_contact_confidence,
  r.name AS resume_name, r.file_url AS resume_url
FROM public.job_applications a
JOIN public.job_listings j ON a.job_listing_id = j.id
LEFT JOIN public.resumes r ON a.resume_id = r.id;


-- ──────────────────────────────────────────────────────────
-- >>> 13_experience_in_view.sql
-- ──────────────────────────────────────────────────────────
-- Exposes experience_level / min_experience / max_experience through the
-- application_details view (columns have existed on job_listings since the
-- base schema). Populated during discovery by services/experience.py.
-- Self-sufficient regardless of whether 05/06/12 already ran — re-adds every
-- column the rebuilt view selects, not just the experience ones.
DO $$ BEGIN
  CREATE TYPE experience_level AS ENUM ('entry', 'mid', 'senior', 'lead', 'principal', 'executive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE public.job_listings
  ADD COLUMN IF NOT EXISTS experience_level experience_level,
  ADD COLUMN IF NOT EXISTS min_experience INTEGER,
  ADD COLUMN IF NOT EXISTS max_experience INTEGER,
  ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS expired_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS expiry_reason TEXT,
  ADD COLUMN IF NOT EXISTS hr_name TEXT,
  ADD COLUMN IF NOT EXISTS hr_email TEXT,
  ADD COLUMN IF NOT EXISTS hr_linkedin_url TEXT,
  ADD COLUMN IF NOT EXISTS hr_linkedin_search_url TEXT,
  ADD COLUMN IF NOT EXISTS hr_contact_source TEXT,
  ADD COLUMN IF NOT EXISTS hr_contact_confidence SMALLINT;

DROP VIEW IF EXISTS public.application_details;
CREATE OR REPLACE VIEW public.application_details AS
SELECT
  a.*,
  j.title AS job_title, j.company AS job_company,
  j.company_logo_url, j.location AS job_location,
  j.work_mode AS job_work_mode, j.job_type,
  j.experience_level, j.min_experience, j.max_experience,
  j.salary_min, j.salary_max, j.salary_currency,
  j.source_platform, j.source_url, j.apply_url,
  j.is_easy_apply, j.required_skills AS job_required_skills, j.jd_text,
  j.posted_at AS job_posted_at,
  j.discovered_at AS job_discovered_at,
  j.is_active AS job_is_active,
  j.expired_at AS job_expired_at,
  j.expiry_reason AS job_expiry_reason,
  j.hr_name, j.hr_email, j.hr_linkedin_url,
  j.hr_linkedin_search_url, j.hr_contact_source, j.hr_contact_confidence,
  r.name AS resume_name, r.file_url AS resume_url
FROM public.job_applications a
JOIN public.job_listings j ON a.job_listing_id = j.id
LEFT JOIN public.resumes r ON a.resume_id = r.id;

-- ──────────────────────────────────────────────────────────
-- >>> 14_new_sources.sql
-- ──────────────────────────────────────────────────────────
-- Jobicy + Himalayas remote boards. Workable/SmartRecruiters/Recruitee ride
-- the ATS aggregator under 'company_portal' (no enum change needed).
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'jobicy';
ALTER TYPE platform ADD VALUE IF NOT EXISTS 'himalayas';
