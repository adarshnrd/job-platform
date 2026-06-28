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
