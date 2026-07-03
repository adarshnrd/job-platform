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
