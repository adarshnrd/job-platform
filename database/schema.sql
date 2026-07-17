-- ============================================================
-- AI Job Platform — Complete Database Schema
-- PostgreSQL 15 + pgvector extension
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================
-- ENUMS
-- ============================================================
CREATE TYPE application_status AS ENUM (
  'discovered','matched','queued','applying','applied',
  'under_review','assessment','interview_scheduled',
  'technical_round','hr_round','offer_received',
  'rejected','withdrawn','accepted'
);
CREATE TYPE match_tier AS ENUM ('auto_apply','recommended','watchlist','archived');
CREATE TYPE platform AS ENUM (
  'linkedin','naukri','indeed','wellfound','hirist',
  'instahyre','cutshort','glassdoor','foundit','remoteok',
  'weworkremotely','dice','ziprecruiter','angellist',
  'company_portal','other'
);
CREATE TYPE notification_type AS ENUM (
  'application_submitted','job_match','interview_scheduled',
  'assessment_received','offer_received','rejection',
  'follow_up_reminder','profile_suggestion','skill_gap'
);
CREATE TYPE job_type AS ENUM ('full_time','part_time','contract','freelance','internship');
CREATE TYPE work_mode AS ENUM ('remote','hybrid','onsite');
CREATE TYPE experience_level AS ENUM ('entry','mid','senior','lead','principal','executive');

-- ============================================================
-- USERS
-- ============================================================
CREATE TABLE public.users (
  id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email TEXT NOT NULL UNIQUE,
  full_name TEXT,
  avatar_url TEXT,
  headline TEXT,
  location TEXT,
  phone TEXT,
  linkedin_url TEXT,
  github_url TEXT,
  portfolio_url TEXT,
  experience_years INTEGER DEFAULT 0,
  current_salary INTEGER,
  expected_salary_min INTEGER,
  expected_salary_max INTEGER,
  preferred_locations TEXT[] DEFAULT '{}',
  preferred_work_modes work_mode[] DEFAULT '{}',
  preferred_job_types job_type[] DEFAULT '{}',
  open_to_remote BOOLEAN DEFAULT TRUE,
  notice_period_days INTEGER DEFAULT 30,
  skills TEXT[] DEFAULT '{}',
  tech_stack JSONB DEFAULT '{}',
  career_goals TEXT,
  auto_apply_enabled BOOLEAN DEFAULT FALSE,
  auto_apply_threshold INTEGER DEFAULT 80,
  preferred_platforms platform[] DEFAULT '{}',
  is_onboarded BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- RESUMES
-- ============================================================
CREATE TABLE public.resumes (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  file_url TEXT NOT NULL,
  file_size INTEGER,
  file_type TEXT DEFAULT 'application/pdf',
  is_primary BOOLEAN DEFAULT FALSE,
  is_active BOOLEAN DEFAULT TRUE,
  parsed_data JSONB DEFAULT '{}',
  ats_score INTEGER,
  word_count INTEGER,
  version INTEGER DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_resumes_primary ON public.resumes(user_id) WHERE is_primary = TRUE;

-- ============================================================
-- JOB LISTINGS
-- ============================================================
CREATE TABLE public.job_listings (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  title TEXT NOT NULL,
  company TEXT NOT NULL,
  company_logo_url TEXT,
  company_website TEXT,
  location TEXT,
  work_mode work_mode,
  job_type job_type DEFAULT 'full_time',
  experience_level experience_level,
  min_experience INTEGER,
  max_experience INTEGER,
  salary_min INTEGER,
  salary_max INTEGER,
  salary_currency TEXT DEFAULT 'INR',
  jd_text TEXT NOT NULL,
  jd_html TEXT,
  required_skills TEXT[] DEFAULT '{}',
  nice_to_have_skills TEXT[] DEFAULT '{}',
  source_platform platform NOT NULL,
  source_url TEXT NOT NULL UNIQUE,
  source_job_id TEXT,
  apply_url TEXT,
  application_deadline TIMESTAMPTZ,
  is_easy_apply BOOLEAN DEFAULT FALSE,
  is_active BOOLEAN DEFAULT TRUE,
  is_remote_friendly BOOLEAN DEFAULT FALSE,
  views_count INTEGER DEFAULT 0,
  applicants_count INTEGER,
  hiring_manager TEXT,
  hiring_manager_url TEXT,
  company_size TEXT,
  company_industry TEXT,
  -- HR contact (enriched by services/hr_contact.py). hr_email / hr_linkedin_url
  -- are verified-only (provider-sourced); hr_linkedin_search_url is a keyless
  -- people-search link. See migration 12_hr_contact.sql.
  hr_name TEXT,
  hr_email TEXT,
  hr_linkedin_url TEXT,
  hr_linkedin_search_url TEXT,
  hr_contact_source TEXT,
  hr_contact_confidence SMALLINT,
  discovered_at TIMESTAMPTZ DEFAULT NOW(),
  last_seen_at TIMESTAMPTZ DEFAULT NOW(),
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_job_listings_platform ON public.job_listings(source_platform);
CREATE INDEX idx_job_listings_active ON public.job_listings(is_active);
CREATE INDEX idx_job_listings_discovered ON public.job_listings(discovered_at DESC);
CREATE INDEX idx_job_listings_skills ON public.job_listings USING GIN(required_skills);

-- ============================================================
-- EMBEDDINGS (pgvector)
-- ============================================================
CREATE TABLE public.job_embeddings (
  job_listing_id UUID PRIMARY KEY REFERENCES public.job_listings(id) ON DELETE CASCADE,
  embedding vector(1536) NOT NULL,
  model TEXT DEFAULT 'text-embedding-3-small',
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_job_embeddings_vector ON public.job_embeddings
  USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE TABLE public.user_embeddings (
  user_id UUID PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
  embedding vector(1536) NOT NULL,
  model TEXT DEFAULT 'text-embedding-3-small',
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- JOB APPLICATIONS
-- ============================================================
CREATE TABLE public.job_applications (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  job_listing_id UUID NOT NULL REFERENCES public.job_listings(id),
  resume_id UUID REFERENCES public.resumes(id),
  match_score INTEGER NOT NULL DEFAULT 0,
  match_tier match_tier NOT NULL,
  match_analysis JSONB DEFAULT '{}',
  skill_gaps TEXT[] DEFAULT '{}',
  missing_skills TEXT[] DEFAULT '{}',
  status application_status DEFAULT 'matched',
  cover_letter TEXT,
  cover_letter_url TEXT,
  tailored_resume_url TEXT,
  applied_at TIMESTAMPTZ,
  application_id TEXT,
  confirmation_screenshot_url TEXT,
  applied_via TEXT DEFAULT 'auto',
  interview_date TIMESTAMPTZ,
  interview_notes TEXT,
  interviewer_name TEXT,
  offered_salary INTEGER,
  offer_deadline TIMESTAMPTZ,
  is_starred BOOLEAN DEFAULT FALSE,
  notes TEXT,
  rejection_reason TEXT,
  follow_up_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_applications_unique ON public.job_applications(user_id, job_listing_id);
CREATE INDEX idx_applications_user ON public.job_applications(user_id);
CREATE INDEX idx_applications_status ON public.job_applications(status);
CREATE INDEX idx_applications_score ON public.job_applications(match_score DESC);
CREATE INDEX idx_applications_applied ON public.job_applications(applied_at DESC);

-- ============================================================
-- STATUS HISTORY
-- ============================================================
CREATE TABLE public.application_status_history (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  application_id UUID NOT NULL REFERENCES public.job_applications(id) ON DELETE CASCADE,
  old_status application_status,
  new_status application_status NOT NULL,
  changed_by TEXT DEFAULT 'system',
  note TEXT,
  metadata JSONB DEFAULT '{}',
  changed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_status_history_app ON public.application_status_history(application_id);

-- ============================================================
-- INTERVIEW PREP
-- ============================================================
CREATE TABLE public.interview_prep (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  application_id UUID NOT NULL REFERENCES public.job_applications(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  technical_questions JSONB DEFAULT '[]',
  behavioral_questions JSONB DEFAULT '[]',
  system_design_questions JSONB DEFAULT '[]',
  coding_challenges JSONB DEFAULT '[]',
  company_research JSONB DEFAULT '{}',
  preparation_plan TEXT,
  key_talking_points TEXT[] DEFAULT '{}',
  salary_negotiation JSONB DEFAULT '{}',
  completed_questions INTEGER DEFAULT 0,
  total_questions INTEGER DEFAULT 0,
  prep_score INTEGER DEFAULT 0,
  last_practiced_at TIMESTAMPTZ,
  generated_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_interview_prep_app ON public.interview_prep(application_id);

-- ============================================================
-- PLATFORM CREDENTIALS (use Supabase Vault in prod)
-- ============================================================
CREATE TABLE public.platform_credentials (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  platform platform NOT NULL,
  encrypted_username TEXT,
  encrypted_password TEXT,
  oauth_token TEXT,
  session_cookies JSONB DEFAULT '{}',
  is_verified BOOLEAN DEFAULT FALSE,
  last_used_at TIMESTAMPTZ,
  last_verified_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_credentials_user_platform ON public.platform_credentials(user_id, platform);

-- ============================================================
-- NOTIFICATIONS
-- ============================================================
CREATE TABLE public.notifications (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  type notification_type NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  payload JSONB DEFAULT '{}',
  action_url TEXT,
  is_read BOOLEAN DEFAULT FALSE,
  is_sent_email BOOLEAN DEFAULT FALSE,
  email_sent_at TIMESTAMPTZ,
  read_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_notifications_user ON public.notifications(user_id, is_read);
CREATE INDEX idx_notifications_created ON public.notifications(created_at DESC);

-- ============================================================
-- QUEUES
-- ============================================================
CREATE TABLE public.discovery_queue (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  search_query TEXT NOT NULL,
  platform platform NOT NULL,
  status TEXT DEFAULT 'pending',
  jobs_found INTEGER DEFAULT 0,
  jobs_matched INTEGER DEFAULT 0,
  error_msg TEXT,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE public.apply_queue (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  application_id UUID NOT NULL REFERENCES public.job_applications(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  priority INTEGER DEFAULT 5,
  attempts INTEGER DEFAULT 0,
  max_attempts INTEGER DEFAULT 3,
  status TEXT DEFAULT 'pending',
  error_msg TEXT,
  next_attempt_at TIMESTAMPTZ DEFAULT NOW(),
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_apply_queue_status ON public.apply_queue(status, next_attempt_at);

-- ============================================================
-- ANALYTICS
-- ============================================================
CREATE TABLE public.analytics_snapshots (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  snapshot_date DATE NOT NULL DEFAULT CURRENT_DATE,
  total_applied INTEGER DEFAULT 0,
  total_matched INTEGER DEFAULT 0,
  total_interviews INTEGER DEFAULT 0,
  total_offers INTEGER DEFAULT 0,
  total_rejected INTEGER DEFAULT 0,
  response_rate NUMERIC(5,2),
  interview_rate NUMERIC(5,2),
  offer_rate NUMERIC(5,2),
  platform_breakdown JSONB DEFAULT '{}',
  skill_demand JSONB DEFAULT '{}',
  avg_match_score NUMERIC(5,2),
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX idx_analytics_user_date ON public.analytics_snapshots(user_id, snapshot_date);

-- ============================================================
-- TRIGGERS
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = NOW(); RETURN NEW; END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON public.users FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_resumes_updated_at BEFORE UPDATE ON public.resumes FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_applications_updated_at BEFORE UPDATE ON public.job_applications FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE OR REPLACE FUNCTION track_application_status_change()
RETURNS TRIGGER AS $$
BEGIN
  IF OLD.status IS DISTINCT FROM NEW.status THEN
    INSERT INTO public.application_status_history(application_id,old_status,new_status,changed_by)
    VALUES(NEW.id,OLD.status,NEW.status,'system');
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_track_status
  AFTER UPDATE OF status ON public.job_applications
  FOR EACH ROW EXECUTE FUNCTION track_application_status_change();

CREATE OR REPLACE FUNCTION enforce_single_primary_resume()
RETURNS TRIGGER AS $$
BEGIN
  IF NEW.is_primary = TRUE THEN
    UPDATE public.resumes SET is_primary = FALSE WHERE user_id = NEW.user_id AND id != NEW.id;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_single_primary_resume
  BEFORE INSERT OR UPDATE OF is_primary ON public.resumes
  FOR EACH ROW EXECUTE FUNCTION enforce_single_primary_resume();

-- ============================================================
-- VIEWS
-- ============================================================
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
  j.hr_name, j.hr_email, j.hr_linkedin_url,
  j.hr_linkedin_search_url, j.hr_contact_source, j.hr_contact_confidence,
  r.name AS resume_name, r.file_url AS resume_url
FROM public.job_applications a
JOIN public.job_listings j ON a.job_listing_id = j.id
LEFT JOIN public.resumes r ON a.resume_id = r.id;

-- ============================================================
-- HELPER FUNCTIONS
-- ============================================================
CREATE OR REPLACE FUNCTION get_pipeline_stats(p_user_id UUID)
RETURNS TABLE(status application_status, count BIGINT) AS $$
BEGIN
  RETURN QUERY SELECT a.status, COUNT(*)::BIGINT
  FROM public.job_applications a WHERE a.user_id = p_user_id GROUP BY a.status;
END; $$ LANGUAGE plpgsql SECURITY DEFINER;

-- ============================================================
-- COMPANY BLACKLIST
-- ============================================================
CREATE TABLE IF NOT EXISTS public.company_blacklist (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  company_name TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_blacklist_user_company
  ON public.company_blacklist(user_id, LOWER(company_name));
CREATE INDEX IF NOT EXISTS idx_blacklist_user ON public.company_blacklist(user_id);

CREATE OR REPLACE FUNCTION find_similar_jobs(p_user_id UUID, p_limit INTEGER DEFAULT 20)
RETURNS TABLE(job_id UUID, similarity FLOAT) AS $$
DECLARE v_user_embedding vector(1536);
BEGIN
  SELECT embedding INTO v_user_embedding FROM public.user_embeddings WHERE user_id = p_user_id;
  IF v_user_embedding IS NULL THEN RETURN; END IF;
  RETURN QUERY
  SELECT je.job_listing_id, 1 - (je.embedding <=> v_user_embedding) AS similarity
  FROM public.job_embeddings je
  JOIN public.job_listings jl ON je.job_listing_id = jl.id
  WHERE jl.is_active = TRUE
    AND NOT EXISTS (SELECT 1 FROM public.job_applications a WHERE a.user_id = p_user_id AND a.job_listing_id = je.job_listing_id)
  ORDER BY je.embedding <=> v_user_embedding LIMIT p_limit;
END; $$ LANGUAGE plpgsql SECURITY DEFINER;
