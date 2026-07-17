-- ============================================================
-- Migration 12 — HR contact per listing
-- Adds a hiring contact (email / LinkedIn) to job_listings and exposes it
-- through the application_details view. Idempotent.
--
-- Populated by services/hr_contact.py during discovery:
--   • hr_linkedin_search_url — a keyless LinkedIn people-search deep-link,
--     always present (a URL the user clicks, not a scraped profile).
--   • hr_email / hr_linkedin_url / hr_name — VERIFIED data, set only when an
--     enrichment provider key (HUNTER/APOLLO/PROXYCURL) is configured. Never a
--     guessed address.
--   • hr_contact_source — 'hunter' | 'apollo' | 'proxycurl' | 'search'
--   • hr_contact_confidence — 0..100 for verified data, else NULL
--
-- Prerequisite: run after 05_recency_relevance.sql and 06_listing_validation.sql
-- (they add the posted_at / is_active / expired_at columns this view selects).
-- PENDING_MIGRATIONS_BUNDLE.sql already sequences them ahead of this.
-- ============================================================

-- ── Contact columns on job_listings ──
ALTER TABLE public.job_listings
  ADD COLUMN IF NOT EXISTS hr_name TEXT,
  ADD COLUMN IF NOT EXISTS hr_email TEXT,
  ADD COLUMN IF NOT EXISTS hr_linkedin_url TEXT,
  ADD COLUMN IF NOT EXISTS hr_linkedin_search_url TEXT,
  ADD COLUMN IF NOT EXISTS hr_contact_source TEXT,
  ADD COLUMN IF NOT EXISTS hr_contact_confidence SMALLINT;

-- ── Expose the HR contact through the view ──
-- Rebuilt from the migration-06 shape, adding the hr_* columns at the end.
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
