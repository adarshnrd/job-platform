"use client";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { InterviewPrep, Application } from "@/types";
import { BookOpen, Code, Users, Cpu, ChevronDown, ChevronUp, Sparkles, ExternalLink } from "lucide-react";
import { cn, formatSalary } from "@/lib/utils";
import toast from "react-hot-toast";
import ReactMarkdown from "react-markdown";

export function InterviewClient({ userId }: { userId: string }) {
  const searchParams = useSearchParams();
  const preselectedAppId = searchParams.get("app");
  const supabase = createClient();

  const [applications, setApplications] = useState<Application[]>([]);
  const [selectedAppId, setSelectedAppId] = useState<string>(preselectedAppId || "");
  const [prep, setPrep] = useState<InterviewPrep | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<"technical" | "behavioral" | "system" | "coding" | "company">("technical");
  const [expandedQ, setExpandedQ] = useState<number | null>(null);
  const [copilotMsg, setCopilotMsg] = useState("");
  const [copilotResp, setCopilotResp] = useState("");
  const [copilotLoading, setCopilotLoading] = useState(false);

  useEffect(() => {
    supabase.from("application_details")
      .select("*").eq("user_id", userId)
      .not("status", "in", '("matched","queued","discovered")')
      .order("applied_at", { ascending: false })
      .then(({ data }) => {
        setApplications(data || []);
        if (preselectedAppId && !selectedAppId) setSelectedAppId(preselectedAppId);
      });
  }, [userId]);

  useEffect(() => {
    if (!selectedAppId) return;
    setPrep(null);
    setLoading(true);
    api.applications.interviewPrep(selectedAppId)
      .then(data => setPrep(data))
      .catch(e => toast.error(e.message || "Failed to load prep"))
      .finally(() => setLoading(false));
  }, [selectedAppId]);

  const sendCopilot = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!copilotMsg.trim()) return;
    setCopilotLoading(true);
    try {
      const { response } = await api.ai.copilot(copilotMsg, "interview");
      setCopilotResp(response);
      setCopilotMsg("");
    } catch (e: any) { toast.error(e.message); }
    finally { setCopilotLoading(false); }
  };

  const selectedApp = applications.find(a => a.id === selectedAppId);

  const TABS = [
    { id: "technical",  label: "Technical",   icon: Code,   count: prep?.technical_questions?.length },
    { id: "behavioral", label: "Behavioral",  icon: Users,  count: prep?.behavioral_questions?.length },
    { id: "system",     label: "System Design",icon: Cpu,    count: prep?.system_design_questions?.length },
    { id: "coding",     label: "Coding",      icon: BookOpen,count: prep?.coding_challenges?.length },
    { id: "company",    label: "Company",     icon: Sparkles,count: undefined },
  ] as const;

  return (
    <div className="space-y-5">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold">Interview Prep Hub</h1>
        <p className="text-sm text-zinc-400 mt-0.5">AI-generated preparation for every application</p>
      </div>

      <div className="grid grid-cols-3 gap-6">
        {/* Left — select application */}
        <div className="col-span-1 space-y-3">
          <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">Select Application</h2>
          {applications.length === 0 ? (
            <div className="card p-4 text-center text-xs text-zinc-500">Apply to some jobs first</div>
          ) : (
            <div className="space-y-2 max-h-[calc(100vh-200px)] overflow-y-auto pr-1">
              {applications.map(app => (
                <button key={app.id} onClick={() => setSelectedAppId(app.id)}
                  className={cn("w-full text-left card p-3 hover:border-zinc-600 transition-colors",
                    selectedAppId === app.id ? "border-amber-500/50 bg-amber-500/5" : "")}>
                  <p className="text-sm font-medium truncate">{app.job_title}</p>
                  <p className="text-xs text-zinc-500 truncate">{app.job_company}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs text-amber-400 font-mono">{app.match_score}%</span>
                    <span className="text-xs text-zinc-600 capitalize">{app.status?.replace("_", " ")}</span>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Right — prep content */}
        <div className="col-span-2 space-y-4">
          {!selectedAppId ? (
            <div className="card p-12 text-center text-zinc-500">
              <BookOpen size={32} className="mx-auto mb-3 opacity-30" />
              <p>Select an application to generate prep material</p>
            </div>
          ) : loading ? (
            <div className="card p-12 text-center">
              <div className="text-zinc-400 animate-pulse">
                <Sparkles size={32} className="mx-auto mb-3" />
                <p className="font-medium">Generating interview prep with AI...</p>
                <p className="text-xs text-zinc-600 mt-1">This may take 15–30 seconds</p>
              </div>
            </div>
          ) : prep ? (
            <>
              {/* Job summary */}
              {selectedApp && (
                <div className="card p-4 flex items-center gap-4">
                  <div className="flex-1">
                    <p className="font-semibold">{selectedApp.job_title}</p>
                    <p className="text-sm text-zinc-400">{selectedApp.job_company}</p>
                  </div>
                  {selectedApp.source_url && (
                    <a href={selectedApp.source_url} target="_blank" rel="noopener noreferrer"
                      className="btn-ghost text-xs flex items-center gap-1">
                      <ExternalLink size={11} /> View JD
                    </a>
                  )}
                </div>
              )}

              {/* Talking points */}
              {prep.key_talking_points?.length > 0 && (
                <div className="card p-4">
                  <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-2">Key Talking Points</p>
                  <div className="flex flex-wrap gap-2">
                    {prep.key_talking_points.map((pt, i) => (
                      <span key={i} className="text-xs bg-amber-500/10 text-amber-300 border border-amber-500/20 px-2.5 py-1 rounded-full">{pt}</span>
                    ))}
                  </div>
                </div>
              )}

              {/* Tabs */}
              <div className="card overflow-hidden">
                <div className="flex border-b border-zinc-800 overflow-x-auto">
                  {TABS.map(({ id, label, icon: Icon, count }) => (
                    <button key={id} onClick={() => { setActiveTab(id as any); setExpandedQ(null); }}
                      className={cn("flex items-center gap-1.5 px-4 py-3 text-sm border-b-2 whitespace-nowrap transition-colors flex-shrink-0",
                        activeTab === id ? "border-amber-500 text-amber-400" : "border-transparent text-zinc-500 hover:text-zinc-300")}>
                      <Icon size={13} />
                      {label}
                      {count != null && count > 0 && (
                        <span className="text-xs bg-zinc-800 px-1.5 py-0.5 rounded-full">{count}</span>
                      )}
                    </button>
                  ))}
                </div>

                <div className="p-4 max-h-[480px] overflow-y-auto">
                  {/* Technical Questions */}
                  {activeTab === "technical" && (
                    <QuestionList questions={prep.technical_questions} expandedQ={expandedQ} setExpandedQ={setExpandedQ} />
                  )}

                  {/* Behavioral Questions */}
                  {activeTab === "behavioral" && (
                    <QuestionList questions={prep.behavioral_questions} expandedQ={expandedQ} setExpandedQ={setExpandedQ} isSTAR />
                  )}

                  {/* System Design */}
                  {activeTab === "system" && (
                    <div className="space-y-3">
                      {(prep.system_design_questions || []).map((q: any, i: number) => (
                        <div key={i} className="bg-zinc-800/50 rounded-lg p-4">
                          <p className="font-medium text-sm mb-2">{q.question}</p>
                          {q.approach && <p className="text-xs text-zinc-400 mb-2"><span className="text-zinc-300">Approach:</span> {q.approach}</p>}
                          {q.key_points?.length > 0 && (
                            <ul className="list-disc list-inside text-xs text-zinc-400 space-y-0.5">
                              {q.key_points.map((pt: string, j: number) => <li key={j}>{pt}</li>)}
                            </ul>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Coding Challenges */}
                  {activeTab === "coding" && (
                    <div className="space-y-3">
                      {(prep.coding_challenges || []).map((c: any, i: number) => (
                        <div key={i} className="bg-zinc-800/50 rounded-lg p-4">
                          <p className="font-medium text-sm">{c.title}</p>
                          <p className="text-xs text-zinc-400 mt-1">{c.description}</p>
                          {c.topics?.length > 0 && (
                            <div className="flex gap-1.5 mt-2 flex-wrap">
                              {c.topics.map((t: string, j: number) => (
                                <span key={j} className="text-xs bg-blue-900/30 text-blue-300 px-2 py-0.5 rounded">{t}</span>
                              ))}
                            </div>
                          )}
                          {c.hints?.length > 0 && (
                            <details className="mt-2">
                              <summary className="text-xs text-zinc-500 cursor-pointer">Show hints</summary>
                              <ul className="list-disc list-inside text-xs text-zinc-400 mt-1 space-y-0.5">
                                {c.hints.map((h: string, j: number) => <li key={j}>{h}</li>)}
                              </ul>
                            </details>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Company Research */}
                  {activeTab === "company" && prep.company_research && (
                    <div className="space-y-4">
                      {prep.company_research.interview_style && (
                        <div className="bg-zinc-800/50 rounded-lg p-4">
                          <p className="text-xs font-semibold text-zinc-400 uppercase mb-1">Interview Style</p>
                          <p className="text-sm">{prep.company_research.interview_style}</p>
                        </div>
                      )}
                      {prep.company_research.culture_notes && (
                        <div className="bg-zinc-800/50 rounded-lg p-4">
                          <p className="text-xs font-semibold text-zinc-400 uppercase mb-1">Culture</p>
                          <p className="text-sm">{prep.company_research.culture_notes}</p>
                        </div>
                      )}
                      {prep.company_research.questions_to_ask?.length > 0 && (
                        <div className="bg-zinc-800/50 rounded-lg p-4">
                          <p className="text-xs font-semibold text-zinc-400 uppercase mb-2">Questions to Ask Them</p>
                          <ul className="space-y-1.5">
                            {prep.company_research.questions_to_ask.map((q: string, i: number) => (
                              <li key={i} className="flex gap-2 text-sm">
                                <span className="text-amber-500 font-mono text-xs mt-0.5">→</span>
                                <span>{q}</span>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}
                      {prep.salary_negotiation?.talking_points?.length > 0 && (
                        <div className="bg-zinc-800/50 rounded-lg p-4">
                          <p className="text-xs font-semibold text-zinc-400 uppercase mb-2">Salary Negotiation</p>
                          {prep.salary_negotiation.target_range && (
                            <p className="text-sm mb-2"><span className="text-zinc-400">Target range:</span> {prep.salary_negotiation.target_range}</p>
                          )}
                          <ul className="space-y-1 text-xs text-zinc-400">
                            {prep.salary_negotiation.talking_points.map((p: string, i: number) => <li key={i}>• {p}</li>)}
                          </ul>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Prep plan */}
              {prep.preparation_plan && (
                <div className="card p-4">
                  <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">Preparation Plan</p>
                  <div className="prose prose-invert prose-xs max-w-none text-zinc-300 text-xs leading-relaxed">
                    <ReactMarkdown>{prep.preparation_plan}</ReactMarkdown>
                  </div>
                </div>
              )}
            </>
          ) : null}

          {/* AI Copilot */}
          <div className="card p-4 space-y-3">
            <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider flex items-center gap-1.5">
              <Sparkles size={13} className="text-amber-400" /> AI Career Copilot
            </p>
            {copilotResp && (
              <div className="bg-zinc-800/50 rounded-lg p-3 text-xs text-zinc-300 leading-relaxed">
                <ReactMarkdown>{copilotResp}</ReactMarkdown>
              </div>
            )}
            <form onSubmit={sendCopilot} className="flex gap-2">
              <input value={copilotMsg} onChange={e => setCopilotMsg(e.target.value)}
                placeholder="Ask about salary negotiation, behavioral questions, company culture..."
                className="input text-xs flex-1" />
              <button type="submit" disabled={copilotLoading} className="btn-primary text-xs px-4 disabled:opacity-50">
                {copilotLoading ? "..." : "Ask"}
              </button>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

function QuestionList({ questions, expandedQ, setExpandedQ, isSTAR = false }: {
  questions: any[]; expandedQ: number | null; setExpandedQ: (i: number | null) => void; isSTAR?: boolean;
}) {
  const DIFF_COLORS: Record<string, string> = {
    easy: "text-green-400 bg-green-900/30", medium: "text-amber-400 bg-amber-900/30", hard: "text-red-400 bg-red-900/30"
  };

  if (!questions?.length) return <p className="text-zinc-600 text-sm">No questions generated.</p>;

  return (
    <div className="space-y-2">
      {questions.map((q: any, i: number) => (
        <div key={i} className="bg-zinc-800/50 rounded-lg overflow-hidden">
          <button onClick={() => setExpandedQ(expandedQ === i ? null : i)}
            className="w-full flex items-start gap-3 p-3 text-left hover:bg-zinc-700/30 transition-colors">
            <span className="text-zinc-500 font-mono text-xs mt-0.5 w-5 flex-shrink-0">{i + 1}.</span>
            <span className="flex-1 text-sm">{q.question}</span>
            <div className="flex items-center gap-2 flex-shrink-0">
              {q.difficulty && (
                <span className={cn("text-xs px-1.5 py-0.5 rounded", DIFF_COLORS[q.difficulty] || "text-zinc-400")}>
                  {q.difficulty}
                </span>
              )}
              {q.topic && <span className="text-xs text-zinc-500">{q.topic}</span>}
              {expandedQ === i ? <ChevronUp size={13} className="text-zinc-500" /> : <ChevronDown size={13} className="text-zinc-500" />}
            </div>
          </button>
          {expandedQ === i && (
            <div className="px-4 pb-4 pt-1 border-t border-zinc-700/50">
              <p className="text-xs font-semibold text-zinc-400 mb-1.5">{isSTAR ? "STAR Answer:" : "Ideal Answer:"}</p>
              <p className="text-sm text-zinc-300 leading-relaxed whitespace-pre-line">{q.ideal_answer}</p>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
