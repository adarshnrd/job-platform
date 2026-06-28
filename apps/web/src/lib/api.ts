import { createClient } from "@/lib/supabase/client";

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
    list: (params?: Record<string, any>) => request(`/applications?${new URLSearchParams(params).toString()}`),
    pipeline: () => request<any>("/applications/pipeline"),
    get: (id: string) => request<any>(`/applications/${id}`),
    update: (id: string, data: any) => request<any>(`/applications/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    star: (id: string) => request<any>(`/applications/${id}/star`, { method: "POST" }),
    apply: (id: string) => request<any>(`/applications/${id}/apply`, { method: "POST", body: JSON.stringify({}) }),
    interviewPrep: (id: string) => request<any>(`/applications/${id}/interview-prep`),
    history: (id: string) => request<any>(`/applications/${id}/history`),
    // Assisted apply
    prepare: (id: string, overrides: Record<string, any> = {}) =>
      request<any>(`/applications/${id}/prepare`, { method: "POST", body: JSON.stringify(overrides) }),
    markOpened: (id: string) => request<any>(`/applications/${id}/opened`, { method: "POST", body: JSON.stringify({}) }),
    confirmSubmit: (id: string, confirmationId?: string) =>
      request<any>(`/applications/${id}/confirm-submit`, { method: "POST", body: JSON.stringify({ confirmation_id: confirmationId }) }),
    markFailed: (id: string, reason: string) =>
      request<any>(`/applications/${id}/mark-failed`, { method: "POST", body: JSON.stringify({ reason }) }),
    events: (id: string) => request<any[]>(`/applications/${id}/events`),
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
    get: () => request<any>("/profile/application"),
    save: (data: Record<string, any>) => request<any>("/profile/application", { method: "PUT", body: JSON.stringify(data) }),
    getSkillExperience: () => request<any>("/profile/skill-experience"),
    saveSkillExperience: (data: Record<string, number>) =>
      request<any>("/profile/skill-experience", { method: "PUT", body: JSON.stringify(data) }),
  },
  // Jobs
  jobs: {
    list: (params?: Record<string, any>) => request<any>(`/jobs?${new URLSearchParams(params).toString()}`),
    get: (id: string) => request<any>(`/jobs/${id}`),
    score: (id: string) => request<any>(`/jobs/${id}/score`, { method: "POST" }),
    discover: (data: any) => request<any>("/jobs/discover", { method: "POST", body: JSON.stringify(data) }),
  },
  // Resumes
  resumes: {
    list: () => request<any[]>("/resumes/"),
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
    setPrimary: (id: string) => request<any>(`/resumes/${id}/set-primary`, { method: "POST" }),
    delete: (id: string) => request<any>(`/resumes/${id}`, { method: "DELETE" }),
    tailor: (resumeId: string, jobId: string) => request<any>(`/resumes/${resumeId}/tailor?job_listing_id=${jobId}`, { method: "POST" }),
  },
  // AI
  ai: {
    skillGaps: () => request<any>("/ai/skill-gaps"),
    copilot: (message: string, context = "general") => request<any>("/ai/copilot", { method: "POST", body: JSON.stringify({ message, context }) }),
    coverLetter: (jobId: string, resumeId?: string) => request<any>("/ai/cover-letter", { method: "POST", body: JSON.stringify({ job_listing_id: jobId, resume_id: resumeId }) }),
  },
  // Automation
  automation: {
    queue: () => request<any[]>("/automation/queue"),
    cancelQueue: (id: string) => request<any>(`/automation/queue/${id}`, { method: "DELETE" }),
    updateSettings: (data: any) => request<any>("/automation/settings", { method: "PATCH", body: JSON.stringify(data) }),
    getBlacklist: () => request<any[]>("/automation/blacklist"),
    addToBlacklist: (company_name: string) => request<any>("/automation/blacklist", { method: "POST", body: JSON.stringify({ company_name }) }),
    removeFromBlacklist: (company_name: string) => request<any>(`/automation/blacklist/${encodeURIComponent(company_name)}`, { method: "DELETE" }),
  },
  // Approval queue
  approval: {
    pending: () => request<any[]>("/applications/pending-approval"),
    approve: (id: string) => request<any>(`/applications/${id}/approve`, { method: "POST" }),
    dismiss: (id: string) => request<any>(`/applications/${id}/dismiss`, { method: "POST" }),
  },
  // AI Career Copilot
  copilot: {
    chat: (data: { message: string; context?: string; job_title?: string; company?: string; history?: any[] }) =>
      request<any>("/copilot/chat", { method: "POST", body: JSON.stringify(data) }),
    generateCoverLetter: (application_id: string) =>
      request<any>("/copilot/generate-cover-letter", { method: "POST", body: JSON.stringify({ application_id }) }),
    analyzeResume: () => request<any>("/copilot/analyze-resume", { method: "POST", body: JSON.stringify({}) }),
    careerSuggestions: () => request<any>("/copilot/career-suggestions"),
  },
  // Export
  export: {
    csvUrl: (status?: string) => `${API_BASE}/api/v1/export/applications/csv${status ? `?status=${status}` : ""}`,
    excelUrl: (status?: string) => `${API_BASE}/api/v1/export/applications/excel${status ? `?status=${status}` : ""}`,
  },
  // Session-based authentication
  sessions: {
    platforms: () => request<any[]>("/sessions/platforms"),
    list: () => request<{ sessions: any[] }>("/sessions"),
    get: (platform: string) => request<any>(`/sessions/${platform}`),
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
      request<any>(`/sessions/${platform}`, { method: "DELETE" }),
    audit: () => request<{ events: any[] }>("/sessions/audit"),
  },
};
