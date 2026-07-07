export type ApplicationStatus =
  | "discovered" | "matched" | "queued" | "applying" | "applied"
  | "needs_input" | "manual_apply"
  | "under_review" | "assessment" | "interview_scheduled"
  | "technical_round" | "hr_round" | "offer_received"
  | "rejected" | "withdrawn" | "accepted";

export type MatchTier = "auto_apply" | "recommended" | "watchlist" | "archived";
export type WorkMode = "remote" | "hybrid" | "onsite";
export type JobType = "full_time" | "part_time" | "contract" | "freelance" | "internship";
export type Platform = "linkedin" | "naukri" | "indeed" | "wellfound" | "hirist" | "instahyre" | "cutshort" | "glassdoor" | "foundit" | "remoteok" | "weworkremotely" | "iimjobs" | "timesjobs" | "shine" | "freshersworld" | "ycombinator" | "dice" | "ziprecruiter" | "remotive" | "arbeitnow" | "themuse" | "adzuna" | "jooble" | "jsearch" | "careerjet" | "company_portal" | "other";

export interface DiscoverySource {
  name: Platform;
  regions: string[];
  api_based: boolean;
  requires_key: boolean;
  key_configured: boolean | null;
  login_capable: boolean;
  discoverable: boolean;
}

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

/** One entry of GET /answers — a banked question joined with its saved answer. */
export interface SavedAnswer {
  id: string;                 // question_bank id
  question_text: string;
  question_type: string;
  category: string;
  options?: string[];
  source_platform?: string;
  answer: string | null;      // active answer value, null if unanswered
  answer_source?: string | null;
  times_used: number;
  last_used_at?: string | null;
  is_answered: boolean;
  is_profile_mapped: boolean;
}

/** One entry of GET /answers/pending — a question blocking an application. */
export interface PendingQuestion {
  pending_id: string;
  application_id: string;
  question_id: string;
  question_text: string;
  question_type: string;
  options?: string[];
  category: string;
  job_title?: string;
  job_company?: string;
  source_platform?: string;
  created_at: string;
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

// ── Discovery activity (Search Activity page) ──
export type DiscoveryPhase =
  | "initializing" | "searching" | "analyzing" | "scoring" | "saving"
  | "completed" | "failed";

export interface DiscoverySourceState {
  status: "pending" | "searching" | "done" | "error";
  jobs_found: number;
  jobs_seen?: number;
  duration_ms?: number;
  error: string | null;
}

export interface DiscoveryRun {
  run_id: string;
  user_id: string;
  region: string;
  trigger: "manual" | "scheduled";
  status: "running" | "completed" | "failed";
  phase: DiscoveryPhase;
  started_at: string;
  finished_at: string | null;
  current_source: string | null;
  current_query: string | null;
  sources: Record<string, DiscoverySourceState>;
  counts: { scraped: number; evaluated: number; matched: number; queued: number };
  error: string | null;
}

export interface DiscoveryEvent {
  seq: number;
  ts: string;
  level: "info" | "success" | "error";
  message: string;
}

export interface RecentDiscoveryJob {
  id: string;
  job_title: string;
  job_company: string;
  source_platform: string;
  job_location: string | null;
  match_score: number | null;
  match_tier: string | null;
  status: string;
  created_at: string;
}

// ── Mission-control telemetry (run ledger, scraper health, AI usage) ──

export interface TelemetryRunSource {
  source: string;
  status: string | null;
  jobs_found: number;
  jobs_seen: number;
  duration_ms: number;
  error: string | null;
  finished_at: string;
}

export interface TelemetryRun {
  run_id: string;
  kind: "discovery" | "apply";
  user_id: string;
  trigger: string | null;
  region: string | null;
  status: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  counts: Record<string, number>;
  error: string | null;
  sources: TelemetryRunSource[];
}

export interface SourceHealthDay {
  day: string;
  jobs_seen: number;
  errors: number;
  runs: number;
}

export interface SourceHealth {
  source: string;
  runs: number;
  errors: number;
  success_rate: number | null;
  baseline_yield: number;
  flagged: boolean;
  flag_reason: "insufficient_data" | "consecutive_errors" | "yield_drop" | null;
  latest: {
    status: string | null;
    jobs_seen: number;
    jobs_found: number;
    duration_ms: number;
    error: string | null;
    finished_at: string;
  };
  daily: SourceHealthDay[];
}

export interface AiUsageBucket {
  calls: number;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface AiUsageSummary {
  date: string;
  today: {
    calls: number;
    input_tokens: number;
    output_tokens: number;
    tokens: number;
    cost_usd: number;
  };
  providers: Record<string, AiUsageBucket>;
  features: Record<string, AiUsageBucket>;
  daily: Array<{ day: string; calls: number; tokens: number; cost_usd: number }>;
  budget: {
    token_budget: number;
    usd_budget: number;
    tokens_used: number;
    cost_used: number;
    exceeded: boolean;
  };
}
