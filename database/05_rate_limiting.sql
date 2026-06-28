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
