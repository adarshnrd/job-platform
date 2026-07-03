export type ApplicationStatus =
  | "discovered" | "matched" | "queued" | "applying" | "applied"
  | "under_review" | "assessment" | "interview_scheduled"
  | "technical_round" | "hr_round" | "offer_received"
  | "rejected" | "withdrawn" | "accepted";

export type MatchTier = "auto_apply" | "recommended" | "watchlist" | "archived";
export type WorkMode = "remote" | "hybrid" | "onsite";
export type JobType = "full_time" | "part_time" | "contract" | "freelance" | "internship";
export type Platform = "linkedin" | "naukri" | "indeed" | "wellfound" | "hirist" | "instahyre" | "cutshort" | "glassdoor" | "foundit" | "remoteok" | "weworkremotely" | "company_portal" | "other";

export interface User {
  id: string;
  email: string;
  full_name?: string;
  avatar_url?: string;
  headline?: string;
  phone?: string;
  location?: string;
  experience_years: number;
  skills: string[];
  tech_stack: Record<string, number>;
  career_goals?: string;
  auto_apply_enabled: boolean;
  auto_apply_threshold: number;
  preferred_platforms: Platform[];
  preferred_work_modes: WorkMode[];
  expected_salary_min?: number;
  expected_salary_max?: number;
  notice_period_days: number;
  work_authorization?: string;
  willing_to_relocate?: boolean;
  current_salary?: number;
  is_onboarded: boolean;
}

export interface JobListing {
  id: string;
  title: string;
  company: string;
  company_logo_url?: string;
  location?: string;
  work_mode?: WorkMode;
  job_type: JobType;
  salary_min?: number;
  salary_max?: number;
  salary_currency: string;
  jd_text: string;
  required_skills: string[];
  nice_to_have_skills: string[];
  source_platform: Platform;
  source_url: string;
  apply_url?: string;
  is_easy_apply: boolean;
  discovered_at: string;
}

export interface MatchAnalysis {
  strengths: string[];
  gaps: string[];
  recommendations: string[];
  summary?: string;
  score_breakdown: Record<string, number>;
}

export interface Application {
  id: string;
  user_id: string;
  job_listing_id: string;
  match_score: number;
  match_tier: MatchTier;
  match_analysis: MatchAnalysis;
  skill_gaps: string[];
  missing_skills: string[];
  status: ApplicationStatus;
  cover_letter?: string;
  applied_at?: string;
  application_id?: string;
  is_starred: boolean;
  notes?: string;
  follow_up_at?: string;
  created_at: string;
  updated_at: string;
  // Joined from view
  job_title?: string;
  job_company?: string;
  company_logo_url?: string;
  job_location?: string;
  job_work_mode?: WorkMode;
  salary_min?: number;
  salary_max?: number;
  salary_currency?: string;
  source_platform?: Platform;
  source_url?: string;
  is_easy_apply?: boolean;
  job_required_skills?: string[];
  jd_text?: string;
  job_posted_at?: string;
  job_discovered_at?: string;
  // Listing liveness (from 06_listing_validation migration)
  job_is_active?: boolean;
  job_expired_at?: string;
  job_expiry_reason?: string;
  // Submission tracking (from 03_application_tracking migration)
  submission_status?: "ready" | "opened" | "submitted" | "failed";
  submission_method?: string;
  resume_snapshot?: { name: string; url: string } | null;
  failure_reason?: string;
  applied_via?: string;
  apply_url?: string;
  // Ranking annotations (added by backend)
  recency_bucket?: number;
  recency_label?: string;
  skill_rescued?: boolean;
  rescue_skills?: string[];
}

export interface Resume {
  id: string;
  user_id: string;
  name: string;
  file_url: string;
  file_size?: number;
  is_primary: boolean;
  is_active: boolean;
  parsed_data: Record<string, any>;
  ats_score?: number;
  word_count?: number;
  version: number;
  created_at: string;
}

export interface KanbanColumn {
  id: string;
  title: string;
  statuses: ApplicationStatus[];
  applications: Application[];
  count: number;
}

export interface PipelineStats {
  total_applied: number;
  total_matched: number;
  active_interviews: number;
  offers: number;
  avg_match_score: number;
}

export interface Notification {
  id: string;
  type: string;
  title: string;
  body?: string;
  is_read: boolean;
  action_url?: string;
  created_at: string;
}

export interface ScreeningAnswer {
  question: string;
  answer: string;
  source?: string;
}

/** Response of POST /applications/{id}/prepare — either a ready package or a needs_input request. */
export interface PrepareResponse {
  needs_input?: { field: string; label: string }[];
  submission_status?: string;
  apply_url?: string;
  cover_letter?: string;
  screening_answers?: ScreeningAnswer[];
  form_data?: Record<string, unknown>;
  resume?: { resume_id?: string; name?: string; file_url?: string; version?: number };
  job?: Record<string, unknown>;
  error?: string;
  status_code?: number;
}

/** One entry of GET /sessions — platform session status for dashboard/settings. */
export interface PlatformSession {
  platform: string;
  display_name: string;
  status: string;
  health: string;
  masked_username?: string;
  captured_at?: string;
  expires_at?: string;
  last_used_at?: string;
  last_validated_at?: string;
  use_count?: number;
  success_rate?: number;
}

/** One entry of GET /portals — a job portal's integration capabilities. */
export interface PortalCapability {
  key: string;
  display_name: string;
  tier: "A" | "B" | "C";
  apply_label: "Auto" | "Assisted" | "View only";
  regions: string[];
  search: boolean;
  details: boolean;
  auto_apply: boolean;
  assisted_apply: boolean;
  resume_upload: boolean;
  question_detection: boolean;
  requires_session: boolean;
  requires_key: boolean;
  anti_bot: "low" | "medium" | "high";
  aliases: string[];
  notes: string;
  has_adapter: boolean;
  has_scraper: boolean;
}

export interface InterviewQuestion {
  question: string;
  ideal_answer: string;
  difficulty: "easy" | "medium" | "hard";
  topic?: string;
  competency?: string;
}

export interface InterviewPrep {
  id: string;
  application_id: string;
  technical_questions: InterviewQuestion[];
  behavioral_questions: InterviewQuestion[];
  system_design_questions: any[];
  coding_challenges: any[];
  company_research: Record<string, any>;
  preparation_plan: string;
  key_talking_points: string[];
  salary_negotiation: Record<string, any>;
  total_questions: number;
  completed_questions: number;
}
