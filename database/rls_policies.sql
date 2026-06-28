-- ============================================================
-- Row Level Security Policies
-- ============================================================

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.resumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_listings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.job_applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.application_status_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.interview_prep ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.discovery_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.apply_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analytics_snapshots ENABLE ROW LEVEL SECURITY;

-- Users: read/write own row only
CREATE POLICY "users_self" ON public.users FOR ALL USING (auth.uid() = id);

-- Resumes: own resumes only
CREATE POLICY "resumes_own" ON public.resumes FOR ALL USING (auth.uid() = user_id);

-- Job listings: readable by all authenticated users
CREATE POLICY "job_listings_read" ON public.job_listings FOR SELECT USING (auth.role() = 'authenticated');
CREATE POLICY "job_listings_insert_service" ON public.job_listings FOR INSERT WITH CHECK (auth.role() = 'service_role');
CREATE POLICY "job_listings_update_service" ON public.job_listings FOR UPDATE USING (auth.role() = 'service_role');

-- Applications: own only
CREATE POLICY "applications_own" ON public.job_applications FOR ALL USING (auth.uid() = user_id);

-- Status history: readable via application ownership
CREATE POLICY "status_history_own" ON public.application_status_history FOR SELECT
  USING (EXISTS (SELECT 1 FROM public.job_applications a WHERE a.id = application_status_history.application_id AND a.user_id = auth.uid()));

-- Interview prep: own only
CREATE POLICY "interview_prep_own" ON public.interview_prep FOR ALL USING (auth.uid() = user_id);

-- Credentials: own only
CREATE POLICY "credentials_own" ON public.platform_credentials FOR ALL USING (auth.uid() = user_id);

-- Notifications: own only
CREATE POLICY "notifications_own" ON public.notifications FOR ALL USING (auth.uid() = user_id);

-- Discovery queue: own only
CREATE POLICY "discovery_own" ON public.discovery_queue FOR ALL USING (auth.uid() = user_id);

-- Apply queue: own only
CREATE POLICY "apply_queue_own" ON public.apply_queue FOR ALL USING (auth.uid() = user_id);

-- Analytics: own only
CREATE POLICY "analytics_own" ON public.analytics_snapshots FOR ALL USING (auth.uid() = user_id);

-- Company blacklist: own only
ALTER TABLE public.company_blacklist ENABLE ROW LEVEL SECURITY;
CREATE POLICY "blacklist_own" ON public.company_blacklist FOR ALL USING (auth.uid() = user_id);
