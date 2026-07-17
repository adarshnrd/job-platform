-- ============================================================
-- Migration 13 — experience requirements in application_details
-- job_listings has carried experience_level / min_experience / max_experience
-- since the base schema, but the view never exposed them, so the frontend and
-- the /jobs experience filter could not see them. Populated during discovery
-- by services/experience.py (scraper value > LLM parse > regex fallback).
-- Idempotent, and self-sufficient regardless of which of 05/06/12 already ran —
-- it re-adds every column the rebuilt view selects, not just the experience
-- ones, so it no longer assumes 12_hr_contact.sql was applied first.
-- ============================================================

-- ── Guards for databases older than the base schema ──
DO $$ BEGIN
  CREATE TYPE experience_level AS ENUM ('entry', 'mid', 'senior', 'lead', 'principal', 'executive');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

ALTER TABLE public.job_listings
  ADD COLUMN IF NOT EXISTS experience_level experience_level,
  ADD COLUMN IF NOT EXISTS min_experience INTEGER,
  ADD COLUMN IF NOT EXISTS max_experience INTEGER,
  -- from 05_recency_relevance.sql / 06_listing_validation.sql
  ADD COLUMN IF NOT EXISTS posted_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS expired_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS expiry_reason TEXT,
  -- from 12_hr_contact.sql
  ADD COLUMN IF NOT EXISTS hr_name TEXT,
  ADD COLUMN IF NOT EXISTS hr_email TEXT,
  ADD COLUMN IF NOT EXISTS hr_linkedin_url TEXT,
  ADD COLUMN IF NOT EXISTS hr_linkedin_search_url TEXT,
  ADD COLUMN IF NOT EXISTS hr_contact_source TEXT,
  ADD COLUMN IF NOT EXISTS hr_contact_confidence SMALLINT;

-- ── Expose experience through the view ──
-- Rebuilt from the migration-12 shape, adding the experience columns.
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
