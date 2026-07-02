import { createClient } from "@/lib/supabase/client";
import type {
  Application,
  JobListing,
  Resume,
  User,
  PipelineStats,
  KanbanColumn,
  InterviewPrep,
  PrepareResponse,
  PlatformSession,
} from "@/types";

/** Partial<User> that also allows null so callers can explicitly clear a column. */
type ProfileUpdate = { [K in keyof User]?: User[K] | null };

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function getAuthHeaders() {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session?.access_token) throw new Error("Not authenticated");
  return { Authorization: `Bearer ${session.access_token}`, "Content-Type": "application/json" };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = await getAuthHeaders();
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/v1${path}`, {
      ...options,
      headers: { ...headers, ...(options.headers || {}) },
    });
  } catch {
    throw new Error("Backend API is not running. Start the FastAPI server on port 8000.");
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "Request failed");
  }
  return res.json();
}

export const api = {
  // Applications
  applications: {
    list: (params?: Record<string, string>) =>
      request<{ data: Application[]; total: number; offset: number; limit: number }>(`/applications?${new URLSearchParams(params).toString()}`),
    pipeline: () => request<{ columns: KanbanColumn[]; stats: PipelineStats; pipeline?: KanbanColumn[] }>("/applications/pipeline"),
    get: (id: string) => request<Application>(`/applications/${id}`),
    update: (id: string, data: Partial<Application>) =>
      request<Application>(`/applications/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    star: (id: string) => request<{ is_starred: boolean }>(`/applications/${id}/star`, { method: "POST" }),
    apply: (id: string) => request<{ success: boolean }>(`/applications/${id}/apply`, { method: "POST", body: JSON.stringify({}) }),
    interviewPrep: (id: string) => request<InterviewPrep>(`/applications/${id}/interview-prep`),
    history: (id: string) => request<{ events: Array<{ event: string; timestamp: string; details?: string }> }>(`/applications/${id}/history`),
    // Assisted apply
    prepare: (id: string, overrides: Record<string, unknown> = {}) =>
      request<PrepareResponse>(`/applications/${id}/prepare`, { method: "POST", body: JSON.stringify(overrides) }),
    markOpened: (id: string) => request<{ success: boolean }>(`/applications/${id}/opened`, { method: "POST", body: JSON.stringify({}) }),
    confirmSubmit: (id: string, confirmationId?: string) =>
      request<{ success: boolean }>(`/applications/${id}/confirm-submit`, { method: "POST", body: JSON.stringify({ confirmation_id: confirmationId }) }),
    markFailed: (id: string, reason: string) =>
      request<{ success: boolean }>(`/applications/${id}/mark-failed`, { method: "POST", body: JSON.stringify({ reason }) }),
    events: (id: string) => request<Array<{ event: string; timestamp: string; details?: string }>>(`/applications/${id}/events`),
    draftAnswer: (id: string, question: string) =>
      request<{ question: string; answer: string }>(`/applications/${id}/draft-answer`, {
        method: "POST", body: JSON.stringify({ question }),
      }),
    rephraseAnswer: (id: string, question: string, answer: string) =>
      request<{ question: string; answer: string }>(`/applications/${id}/rephrase-answer`, {
        method: "POST", body: JSON.stringify({ question, answer }),
      }),
    draftCoverLetter: (id: string) =>
      request<{ cover_letter: string }>(`/applications/${id}/draft-cover-letter`, {
        method: "POST", body: JSON.stringify({}),
      }),
    rephraseCoverLetter: (id: string, cover_letter: string) =>
      request<{ cover_letter: string }>(`/applications/${id}/rephrase-cover-letter`, {
        method: "POST", body: JSON.stringify({ cover_letter }),
      }),
    rateLimits: () => request<Record<string, any>>("/applications/rate-limits"),
    checkApplied: (params: { job_listing_id?: string; source_url?: string }) =>
      request<{ already_applied: boolean; application_id?: string; applied_url?: string; source_url?: string }>(
        `/applications/check-applied?${new URLSearchParams(params as any).toString()}`
      ),
  },
  // Application Profile
  profile: {
    get: () => request<User>("/profile/application"),
    save: (data: ProfileUpdate) => request<User>("/profile/application", { method: "PUT", body: JSON.stringify(data) }),
    getSkillExperience: () => request<Record<string, number>>("/profile/skill-experience"),
    saveSkillExperience: (data: Record<string, number>) =>
      request<Record<string, number>>("/profile/skill-experience", { method: "PUT", body: JSON.stringify(data) }),
  },
  // Jobs
  jobs: {
    list: (params?: Record<string, string>) =>
      request<{ data: Application[]; total: number; offset: number; limit: number; matched?: number }>(`/jobs?${new URLSearchParams(params).toString()}`),
    get: (id: string) => request<Application | JobListing>(`/jobs/${id}`),
    score: (id: string) => request<{ success: boolean; match_score: number; tier: string; analysis: Record<string, unknown> }>(`/jobs/${id}/score`, { method: "POST" }),
    discover: (data: Record<string, unknown>) => request<{ success: boolean; message: string }>("/jobs/discover", { method: "POST", body: JSON.stringify(data) }),
  },
  // Resumes
  resumes: {
    list: () => request<Resume[]>("/resumes/"),
    upload: async (formData: FormData) => {
      const headers = await getAuthHeaders();
      let res: Response;
      try {
        res = await fetch(`${API_BASE}/api/v1/resumes/upload`, {
          method: "POST", body: formData,
          headers: { Authorization: headers.Authorization },
        });
      } catch {
        throw new Error("Backend API is not running. Start the FastAPI server on port 8000.");
      }
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || "Upload failed");
      }
      return res.json();
    },
    setPrimary: (id: string) => request<{ success: boolean }>(`/resumes/${id}/set-primary`, { method: "POST" }),
    delete: (id: string) => request<{ success: boolean }>(`/resumes/${id}`, { method: "DELETE" }),
    tailor: (resumeId: string, jobId: string) =>
      request<{ tailoring: Record<string, unknown>; resume_id: string; job_listing_id: string }>(
        `/resumes/${resumeId}/tailor?job_listing_id=${jobId}`, { method: "POST" }
      ),
  },
  // AI
  ai: {
    skillGaps: () => request<{ missing_skills: unknown[]; trending_skills: string[]; market_insights: Record<string, unknown> }>("/ai/skill-gaps"),
    copilot: (message: string, context = "general") =>
      request<{ response: string }>("/ai/copilot", { method: "POST", body: JSON.stringify({ message, context }) }),
    coverLetter: (jobId: string, resumeId?: string) =>
      request<{ cover_letter: string }>("/ai/cover-letter", { method: "POST", body: JSON.stringify({ job_listing_id: jobId, resume_id: resumeId }) }),
  },
  // Automation
  automation: {
    queue: () => request<Array<{ id: string; status: string; platform: string; job_listing_id: string }>>("/automation/queue"),
    cancelQueue: (id: string) => request<{ success: boolean }>(`/automation/queue/${id}`, { method: "DELETE" }),
    updateSettings: (data: Partial<User>) =>
      request<User>("/automation/settings", { method: "PATCH", body: JSON.stringify(data) }),
    getBlacklist: () => request<Array<{ company_name: string }>>("/automation/blacklist"),
    addToBlacklist: (company_name: string) =>
      request<{ success: boolean }>("/automation/blacklist", { method: "POST", body: JSON.stringify({ company_name }) }),
    removeFromBlacklist: (company_name: string) =>
      request<{ success: boolean }>(`/automation/blacklist/${encodeURIComponent(company_name)}`, { method: "DELETE" }),
  },
  // Approval queue
  approval: {
    pending: () => request<Application[]>("/applications/pending-approval"),
    approve: (id: string) => request<{ success: boolean }>(`/applications/${id}/approve`, { method: "POST" }),
    dismiss: (id: string) => request<{ success: boolean }>(`/applications/${id}/dismiss`, { method: "POST" }),
  },
  // AI Career Copilot
  copilot: {
    chat: (data: { message: string; context?: string; job_title?: string; company?: string; history?: Array<{ role: string; content: string }> }) =>
      request<{ response: string; context?: string }>("/copilot/chat", { method: "POST", body: JSON.stringify(data) }),
    generateCoverLetter: (application_id: string) =>
      request<{ cover_letter: string }>("/copilot/generate-cover-letter", { method: "POST", body: JSON.stringify({ application_id }) }),
    analyzeResume: () => request<{ analysis: string }>("/copilot/analyze-resume", { method: "POST", body: JSON.stringify({}) }),
    careerSuggestions: () =>
      request<{ suggestions: string; top_skill_gaps: Array<[string, number]> }>("/copilot/career-suggestions"),
  },
  // Export
  export: {
    csvUrl: (status?: string) => `${API_BASE}/api/v1/export/applications/csv${status ? `?status=${status}` : ""}`,
    excelUrl: (status?: string) => `${API_BASE}/api/v1/export/applications/excel${status ? `?status=${status}` : ""}`,
    jobTrackerUrl: () => `${API_BASE}/api/v1/export/job-tracker`,
  },
  // Session-based authentication
  sessions: {
    platforms: () => request<Array<{ id: string; name: string; supported: boolean }>>("/sessions/platforms"),
    list: () => request<{ sessions: PlatformSession[] }>("/sessions"),
    get: (platform: string) => request<PlatformSession>(`/sessions/${platform}`),
    connect: (platform: string) =>
      request<{ handshake_token: string; poll_url: string; expires_at: string }>(
        `/sessions/${platform}/connect`, { method: "POST", body: JSON.stringify({}) }
      ),
    pollHandshake: (token: string) =>
      request<{ status: string; platform: string; session_id: string | null; error_message: string | null }>(
        `/sessions/handshake/${token}`
      ),
    reconnect: (platform: string) =>
      request<{ handshake_token: string; poll_url: string; expires_at: string }>(
        `/sessions/${platform}/reconnect`, { method: "POST", body: JSON.stringify({}) }
      ),
    refresh: (platform: string) =>
      request<{ valid: boolean; status: any }>(`/sessions/${platform}/refresh`, { method: "POST", body: JSON.stringify({}) }),
    disconnect: (platform: string) =>
      request<{ success: boolean }>(`/sessions/${platform}`, { method: "DELETE" }),
    audit: () => request<{ events: Array<{ event: string; timestamp: string; platform?: string }> }>("/sessions/audit"),
  },
};
