"use client";
import { Fragment, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { Application, ApplicationStatus } from "@/types";
import { STATUS_CONFIG, PLATFORM_LABELS, formatSalary, timeAgo, scoreColor, cn } from "@/lib/utils";
import {
  Star, ExternalLink, BookOpen, ChevronDown, Download,
  FileSpreadsheet, FileText, Search, RefreshCw, Bot, Send, Clock, CheckCircle, AlertTriangle,
  ArrowUp, ArrowDown, ArrowUpDown,
} from "lucide-react";
import toast from "react-hot-toast";
import Link from "next/link";
import { ApplyModal } from "./apply-modal";

const SUBMISSION_BADGE: Record<string, { label: string; cls: string; Icon: any }> = {
  ready: { label: "Ready to apply", cls: "bg-blue-500/15 text-blue-400 border-blue-500/30", Icon: Clock },
  opened: { label: "Opened", cls: "bg-amber-500/15 text-amber-400 border-amber-500/30", Icon: ExternalLink },
  submitted: { label: "Submitted", cls: "bg-green-500/15 text-green-400 border-green-500/30", Icon: CheckCircle },
  failed: { label: "Failed", cls: "bg-red-500/15 text-red-400 border-red-500/30", Icon: AlertTriangle },
};

function SubmissionBadge({ status }: { status?: string }) {
  const badge = status ? SUBMISSION_BADGE[status] : undefined;
  if (!badge) return <span className="text-xs text-zinc-600">Not yet applied</span>;
  const { Icon, cls, label } = badge;
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full border", cls)}>
      <Icon size={11} /> {label}
    </span>
  );
}

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "All statuses" },
  { value: "matched", label: "Matched" },
  { value: "applied", label: "Applied" },
  { value: "under_review", label: "Under Review" },
  { value: "interview_scheduled", label: "Interview" },
  { value: "offer_received", label: "Offer" },
  { value: "rejected", label: "Rejected" },
];

type Bucket = "active" | "history" | "archived";

const BUCKET_TABS: { key: Bucket; label: string; hint: string }[] = [
  { key: "active", label: "Active", hint: "Jobs you can still act on" },
  { key: "history", label: "History", hint: "Everything you've applied to" },
  { key: "archived", label: "Archived", hint: "Expired, removed, or dismissed" },
];

type SortColumn = "status" | "score" | "platform" | "date";
type SortDir = "asc" | "desc";

const SORTABLE_COLUMNS: { key: SortColumn; label: string }[] = [
  { key: "status", label: "Status" },
  { key: "score", label: "Score" },
  { key: "platform", label: "Platform" },
  { key: "date", label: "Date" },
];

const MIN_SCORE_OPTIONS: { value: number; label: string }[] = [
  { value: 50, label: "Score ≥ 50%" },
  { value: 60, label: "Score ≥ 60%" },
  { value: 70, label: "Score ≥ 70%" },
  { value: 80, label: "Score ≥ 80%" },
  { value: 0, label: "All scores" },
];

export function ApplicationsClient({ userId }: { userId: string }) {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [filterStarred, setFilterStarred] = useState(false);
  const [bucket, setBucket] = useState<Bucket>("active");
  const [counts, setCounts] = useState<{ active: number; history: number; archived: number } | null>(null);
  // Tri-state column-header sort: null column = bucket's default ordering.
  const [sortCol, setSortCol] = useState<SortColumn | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [minScore, setMinScore] = useState(50);
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [generatingCover, setGeneratingCover] = useState<string | null>(null);
  const [applyTarget, setApplyTarget] = useState<Application | null>(null);
  const [events, setEvents] = useState({} as Record<string, any[]>);
  const exportRef = useRef<HTMLDivElement>(null);

  const loadEvents = async (id: string) => {
    try {
      const data = await api.applications.events(id);
      setEvents(prev => ({ ...prev, [id]: data || [] }));
    } catch { /* table may not exist pre-migration */ }
  };

  const toggleExpand = (id: string) => {
    const next = expandedId === id ? null : id;
    setExpandedId(next);
    if (next && !events[next]) loadEvents(next);
  };

  const load = async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {
        bucket,
        min_score: String(minScore),
      };
      if (sortCol) { params.sort_by = sortCol; params.sort_dir = sortDir; }
      if (filterStatus) params.status = filterStatus;
      if (filterStarred) params.is_starred = "true";
      if (dateFrom) params.date_from = dateFrom;
      if (dateTo) params.date_to = dateTo;
      const data = await api.applications.list(params);
      setApps(data.data || []);
      if (data.counts) setCounts(data.counts);
    } catch (e: any) {
      toast.error(e.message || "Failed to load");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [filterStatus, filterStarred, bucket, sortCol, sortDir, minScore, dateFrom, dateTo]);

  // Tri-state cycle per column: unsorted → asc → desc → unsorted. Clicking a
  // different column always starts that column fresh at asc.
  const handleSort = (col: SortColumn) => {
    if (sortCol !== col) { setSortCol(col); setSortDir("asc"); return; }
    if (sortDir === "asc") { setSortDir("desc"); return; }
    setSortCol(null);
  };

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) setExportOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleStatusChange = async (id: string, status: ApplicationStatus) => {
    try {
      await api.applications.update(id, { status });
      toast.success("Status updated");
      load();
    } catch (e: any) { toast.error(e.message); }
  };

  const handleStar = async (id: string) => {
    try {
      await api.applications.star(id);
      load();
    } catch (e: any) { toast.error(e.message); }
  };

  const exportFile = async (format: "csv" | "excel") => {
    setExportOpen(false);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) { toast.error("Not authenticated"); return; }
      const url = format === "csv"
        ? api.export.csvUrl(filterStatus || undefined)
        : api.export.excelUrl(filterStatus || undefined);
      const res = await fetch(url, { headers: { Authorization: `Bearer ${session.access_token}` } });
      if (!res.ok) { toast.error("Export failed"); return; }
      const blob = await res.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = format === "csv" ? "applications.csv" : "applications.xlsx";
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (e: any) { toast.error(e.message || "Export failed"); }
  };

  const generateCoverLetter = async (appId: string) => {
    setGeneratingCover(appId);
    try {
      await api.copilot.generateCoverLetter(appId);
      toast.success("Cover letter generated!");
      setExpandedId(appId);
    } catch (e: any) { toast.error(e.message || "Failed to generate cover letter"); }
    finally { setGeneratingCover(null); }
  };

  const filtered = apps.filter(a => {
    const q = search.toLowerCase();
    return !q || (a.job_title || "").toLowerCase().includes(q) || (a.job_company || "").toLowerCase().includes(q);
  });

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Applications</h1>
          <p className="text-sm text-zinc-400 mt-0.5">{apps.length} total · {apps.filter(a => a.status === "applied").length} applied</p>
        </div>
        <div className="flex gap-2 items-center">
          {/* Export dropdown */}
          <div className="relative" ref={exportRef}>
            <button
              onClick={() => setExportOpen(o => !o)}
              className="btn-secondary flex items-center gap-2 text-xs">
              <Download size={13} /> Export <ChevronDown size={11} className={cn("transition-transform", exportOpen ? "rotate-180" : "")} />
            </button>
            {exportOpen && (
              <div className="absolute right-0 mt-1 w-44 bg-zinc-900 border border-zinc-700 rounded-lg shadow-xl z-20 overflow-hidden">
                <button onClick={() => exportFile("csv")}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-xs text-zinc-300 hover:bg-zinc-800 transition-colors">
                  <FileText size={13} className="text-amber-400" /> Export CSV
                </button>
                <button onClick={() => exportFile("excel")}
                  className="w-full flex items-center gap-2.5 px-3 py-2.5 text-xs text-zinc-300 hover:bg-zinc-800 transition-colors">
                  <FileSpreadsheet size={13} className="text-green-400" /> Export Excel
                </button>
              </div>
            )}
          </div>
          <button onClick={load} disabled={loading} className="btn-secondary flex items-center gap-2 text-xs">
            <RefreshCw size={13} className={loading ? "animate-spin" : ""} /> Refresh
          </button>
        </div>
      </div>

      {/* Lifecycle tabs */}
      <div className="flex rounded-lg border border-zinc-800 overflow-hidden w-fit">
        {BUCKET_TABS.map(t => (
          <button key={t.key} onClick={() => setBucket(t.key)} title={t.hint}
            className={cn(
              "px-4 py-2 text-sm flex items-center gap-2 transition-colors",
              bucket === t.key
                ? "bg-amber-500/10 text-amber-400 font-semibold"
                : "bg-zinc-900 text-zinc-400 hover:text-zinc-100"
            )}>
            {t.label}
            {counts && (
              <span className={cn("text-[10px] px-1.5 py-0.5 rounded-full",
                bucket === t.key ? "bg-amber-500/20" : "bg-zinc-800")}>
                {counts[t.key]}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <div className="relative flex-1 min-w-56">
          <Search size={13} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search title or company..." className="input pl-9 text-sm" />
        </div>
        {bucket === "active" && (
          <select value={minScore} onChange={e => setMinScore(Number(e.target.value))} className="input w-auto text-sm">
            {MIN_SCORE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        )}
        <select value={filterStatus} onChange={e => setFilterStatus(e.target.value)} className="input w-auto text-sm">
          {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <button onClick={() => setFilterStarred(s => !s)}
          className={cn("flex items-center gap-2 btn-secondary text-sm", filterStarred ? "border-amber-500/50 text-amber-400" : "")}>
          <Star size={13} fill={filterStarred ? "currentColor" : "none"} /> Starred
        </button>
        <div className="flex items-center gap-1.5">
          <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)}
            max={dateTo || undefined}
            title="From date" className="input w-auto text-sm" />
          <span className="text-xs text-zinc-500">–</span>
          <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)}
            min={dateFrom || undefined}
            title="To date" className="input w-auto text-sm" />
          {(dateFrom || dateTo) && (
            <button onClick={() => { setDateFrom(""); setDateTo(""); }}
              title="Clear date filter"
              className="text-zinc-500 hover:text-zinc-200 text-xs px-1.5">
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Table */}
      {loading ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="card h-14 animate-pulse bg-zinc-800/50" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card p-12 text-center text-zinc-500">No applications found.</div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-zinc-800 text-xs text-zinc-500 uppercase tracking-wider">
                <th className="text-left px-4 py-3 font-medium">Role</th>
                {SORTABLE_COLUMNS.map(col => {
                  const active = sortCol === col.key;
                  const Icon = active ? (sortDir === "asc" ? ArrowUp : ArrowDown) : ArrowUpDown;
                  return (
                    <th key={col.key} className="text-left px-4 py-3 font-medium">
                      <button
                        onClick={() => handleSort(col.key)}
                        className={cn(
                          "flex items-center gap-1 uppercase tracking-wider text-xs font-medium transition-colors",
                          active ? "text-amber-400" : "text-zinc-500 hover:text-zinc-300"
                        )}
                        title={active ? `Sorted ${sortDir === "asc" ? "ascending" : "descending"} — click to ${sortDir === "asc" ? "reverse" : "clear"}` : `Sort by ${col.label}`}
                      >
                        {col.label}
                        <Icon size={12} className={active ? "" : "opacity-40"} />
                      </button>
                    </th>
                  );
                })}
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-800/60">
              {filtered.map(app => (
                <Fragment key={app.id}>
                  <tr
                    className="hover:bg-zinc-800/30 transition-colors cursor-pointer"
                    onClick={() => toggleExpand(app.id)}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <button onClick={(e) => { e.stopPropagation(); handleStar(app.id); }}
                          className={cn("flex-shrink-0", app.is_starred ? "text-amber-400" : "text-zinc-700 hover:text-zinc-400")}>
                          <Star size={13} fill={app.is_starred ? "currentColor" : "none"} />
                        </button>
                        <div>
                          <p className="text-sm font-medium">{app.job_title}</p>
                          <p className="text-xs text-zinc-500">{app.job_company}</p>
                          {bucket === "archived" && (
                            <p className="text-[10px] text-red-400/80 mt-0.5">
                              {app.status === "withdrawn" ? "Dismissed by you" : app.job_expiry_reason || "Listing no longer available"}
                            </p>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={app.status}
                        onChange={(e) => { e.stopPropagation(); handleStatusChange(app.id, e.target.value as ApplicationStatus); }}
                        onClick={e => e.stopPropagation()}
                        className={cn("text-xs rounded px-2 py-1 border-0 cursor-pointer focus:outline-none",
                          STATUS_CONFIG[app.status]?.bg, STATUS_CONFIG[app.status]?.color)}>
                        {Object.entries(STATUS_CONFIG).map(([val, cfg]) => (
                          <option key={val} value={val}>{cfg.label}</option>
                        ))}
                      </select>
                    </td>
                    <td className="px-4 py-3">
                      <span className={cn("font-mono text-sm font-bold", scoreColor(app.match_score))}>
                        {app.match_score}%
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-zinc-400">
                      {app.source_platform ? PLATFORM_LABELS[app.source_platform] || app.source_platform : "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-zinc-500">
                      {app.applied_at ? timeAgo(app.applied_at) : timeAgo(app.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1" onClick={e => e.stopPropagation()}>
                        {app.status === "needs_input" && (
                          <Link href="/answers"
                            title="This application is paused on questions only you can answer"
                            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-blue-400 bg-blue-500/10 hover:bg-blue-500/20 transition-colors">
                            <AlertTriangle size={12} /> Answer now
                          </Link>
                        )}
                        {app.status !== "applied" && app.status !== "offer_received" && app.status !== "rejected" && bucket !== "archived" && (
                          <button onClick={() => setApplyTarget(app)}
                            title="Assisted apply"
                            className="flex items-center gap-1 px-2 py-1 rounded text-xs font-medium text-amber-400 bg-amber-500/10 hover:bg-amber-500/20 transition-colors">
                            <Send size={12} /> Apply
                          </button>
                        )}
                        <Link href={`/interview?app=${app.id}`}
                          className="p-1.5 rounded text-zinc-500 hover:text-amber-400 hover:bg-zinc-800 transition-colors">
                          <BookOpen size={13} />
                        </Link>
                        {app.source_url && (
                          <a href={app.source_url} target="_blank" rel="noopener noreferrer"
                            className="p-1.5 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition-colors">
                            <ExternalLink size={13} />
                          </a>
                        )}
                        <ChevronDown size={13} className={cn("text-zinc-600 transition-transform", expandedId === app.id ? "rotate-180" : "")} />
                      </div>
                    </td>
                  </tr>

                  {/* Expanded row */}
                  {expandedId === app.id && (
                    <tr key={`${app.id}-expanded`} className="bg-zinc-900/60">
                      <td colSpan={6} className="px-4 py-4">
                        <div className="grid grid-cols-3 gap-6 text-sm">
                          {/* Match analysis */}
                          {app.match_analysis?.strengths?.length > 0 && (
                            <div>
                              <p className="text-xs font-semibold text-green-400 mb-2">✓ Strengths</p>
                              <ul className="space-y-1 text-xs text-zinc-400">
                                {app.match_analysis.strengths.map((s, i) => <li key={i}>• {s}</li>)}
                              </ul>
                            </div>
                          )}
                          {app.match_analysis?.gaps?.length > 0 && (
                            <div>
                              <p className="text-xs font-semibold text-red-400 mb-2">⚠ Gaps</p>
                              <ul className="space-y-1 text-xs text-zinc-400">
                                {app.match_analysis.gaps.map((g, i) => <li key={i}>• {g}</li>)}
                              </ul>
                            </div>
                          )}
                          {app.match_analysis?.summary && (
                            <div>
                              <p className="text-xs font-semibold text-zinc-400 mb-2">Summary</p>
                              <p className="text-xs text-zinc-400 leading-relaxed">{app.match_analysis.summary}</p>
                              {app.notes && (
                                <div className="mt-3">
                                  <p className="text-xs font-semibold text-zinc-400 mb-1">Notes</p>
                                  <p className="text-xs text-zinc-500">{app.notes}</p>
                                </div>
                              )}
                            </div>
                          )}
                        </div>

                        {/* Salary + skills */}
                        <div className="flex flex-wrap items-center gap-4 mt-3 pt-3 border-t border-zinc-800">
                          {(app.salary_min || app.salary_max) && (
                            <span className="text-xs text-zinc-500">
                              💰 {formatSalary(app.salary_min, app.salary_max, app.salary_currency)}
                            </span>
                          )}
                          {app.job_work_mode && (
                            <span className="text-xs text-zinc-500 capitalize">🏠 {app.job_work_mode}</span>
                          )}
                          {app.skill_gaps?.length > 0 && (
                            <span className="text-xs text-red-400">Missing: {app.skill_gaps.join(", ")}</span>
                          )}
                          <div className="ml-auto flex gap-2">
                            <button
                              onClick={() => generateCoverLetter(app.id)}
                              disabled={generatingCover === app.id}
                              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 transition-colors disabled:opacity-50">
                              <Bot size={12} className={generatingCover === app.id ? "animate-pulse" : ""} />
                              {generatingCover === app.id ? "Generating..." : "Cover Letter"}
                            </button>
                            <Link href={`/copilot?app=${app.id}&company=${encodeURIComponent(app.job_company || "")}&role=${encodeURIComponent(app.job_title || "")}`}
                              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors">
                              <Bot size={12} /> AI Coach
                            </Link>
                          </div>
                        </div>

                        {/* ── Submission record / audit trail ── */}
                        <div className="mt-4 pt-4 border-t border-zinc-800">
                          <div className="flex items-center justify-between mb-3">
                            <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">Submission Record</p>
                            <SubmissionBadge status={app.submission_status} />
                          </div>

                          <div className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-xs">
                            {app.applied_at && (
                              <div className="flex gap-2"><span className="text-zinc-500">Submitted:</span><span className="text-zinc-300">{new Date(app.applied_at).toLocaleString()}</span></div>
                            )}
                            {app.submission_method && (
                              <div className="flex gap-2"><span className="text-zinc-500">Method:</span><span className="text-zinc-300 capitalize">{app.submission_method}</span></div>
                            )}
                            {app.resume_snapshot?.name && (
                              <div className="flex gap-2"><span className="text-zinc-500">Resume used:</span><span className="text-zinc-300">{app.resume_snapshot.name}</span></div>
                            )}
                            {app.applied_via && (
                              <div className="flex gap-2"><span className="text-zinc-500">Applied via:</span><span className="text-zinc-300">{app.applied_via}</span></div>
                            )}
                            {app.application_id && (
                              <div className="flex gap-2"><span className="text-zinc-500">Confirmation:</span><span className="text-zinc-300 font-mono">{app.application_id}</span></div>
                            )}
                          </div>

                          {app.failure_reason && (
                            <div className="mt-2 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 p-2.5">
                              <AlertTriangle size={13} className="text-red-400 mt-0.5 flex-shrink-0" />
                              <p className="text-xs text-red-300">{app.failure_reason}</p>
                            </div>
                          )}

                          {/* Cover letter submitted */}
                          {app.cover_letter && (
                            <details className="mt-3">
                              <summary className="text-xs text-zinc-400 cursor-pointer hover:text-zinc-200">View cover letter submitted</summary>
                              <p className="mt-2 text-xs text-zinc-400 leading-relaxed whitespace-pre-wrap bg-zinc-800/40 rounded-lg p-3 border border-zinc-700/50">{app.cover_letter}</p>
                            </details>
                          )}

                          {/* Event timeline */}
                          {events[app.id]?.length > 0 && (
                            <div className="mt-3">
                              <p className="text-xs text-zinc-500 mb-2">Activity timeline</p>
                              <div className="space-y-1.5 border-l border-zinc-700/60 pl-3">
                                {events[app.id].map((ev: any) => (
                                  <div key={ev.id} className="text-xs">
                                    <span className="text-zinc-300">{ev.message || ev.event_type}</span>
                                    <span className="text-zinc-600 ml-2">{timeAgo(ev.created_at)}</span>
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Assisted-apply modal */}
      {applyTarget && (
        <ApplyModal
          appId={applyTarget.id}
          jobTitle={applyTarget.job_title || "this role"}
          jobCompany={applyTarget.job_company || "the company"}
          onClose={() => setApplyTarget(null)}
          onUpdated={() => { setApplyTarget(null); load(); }}
        />
      )}
    </div>
  );
}
