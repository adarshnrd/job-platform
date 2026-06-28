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
