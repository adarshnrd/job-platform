"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Application, PortalCapability } from "@/types";
import { JobCard } from "./job-card";
import { Search, Eye, EyeOff } from "lucide-react";
import toast from "react-hot-toast";

const RECENCY_LABELS: Record<number, string> = {
  0: "Posted Today",
  1: "Posted 2 Days Ago",
  2: "Posted This Week",
  3: "Older Posts",
};

export function JobsClient() {
  const [jobs, setJobs] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filterPlatform, setFilterPlatform] = useState("");
  const [filterMode, setFilterMode] = useState("");
  const [filterTier, setFilterTier] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [portals, setPortals] = useState<Record<string, PortalCapability>>({});

  useEffect(() => {
    api.portals.list()
      .then(({ portals }) => {
        const map: Record<string, PortalCapability> = {};
        for (const p of portals) {
          map[p.key] = p;
          for (const alias of p.aliases) map[alias] = p;
        }
        setPortals(map);
      })
      .catch(() => {});
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (filterPlatform) params.platform = filterPlatform;
      if (filterMode) params.work_mode = filterMode;
      if (showArchived) params.show_archived = "true";
      const data = await api.jobs.list(params);
      setJobs(data.data || data.matched || []);
    } catch (e: any) {
      toast.error(e.message || "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [filterPlatform, filterMode, showArchived]);

  const filtered = jobs.filter(j => {
    const q = search.toLowerCase();
    const matchSearch = !q || (j.job_title || "").toLowerCase().includes(q) || (j.job_company || "").toLowerCase().includes(q);
    const matchTier = !filterTier || j.match_tier === filterTier;
    return matchSearch && matchTier;
  });

  const buckets = new Map<number, Application[]>();
  for (const j of filtered) {
    const b = j.recency_bucket ?? 3;
    if (!buckets.has(b)) buckets.set(b, []);
    buckets.get(b)!.push(j);
  }
  const sortedBuckets = [...buckets.entries()].sort(([a], [b]) => a - b);

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Job Matches</h1>
          <p className="text-sm text-zinc-400 mt-0.5">
            {filtered.length} jobs matched to your profile
            {filtered.some(j => j.skill_rescued) && (
              <span className="text-amber-400 ml-1">
                ({filtered.filter(j => j.skill_rescued).length} rescued by skill match)
              </span>
            )}
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <div className="relative flex-1 min-w-64">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search title or company..." className="input pl-9" />
        </div>
        <select value={filterTier} onChange={e => setFilterTier(e.target.value)} className="input w-auto">
          <option value="">All tiers</option>
          <option value="auto_apply">Auto Apply (80%+)</option>
          <option value="recommended">Recommended (60-79%)</option>
          <option value="watchlist">Watchlist (50-59%)</option>
        </select>
        <select value={filterMode} onChange={e => setFilterMode(e.target.value)} className="input w-auto">
          <option value="">All modes</option>
          <option value="remote">Remote</option>
          <option value="hybrid">Hybrid</option>
          <option value="onsite">Onsite</option>
        </select>
        <select value={filterPlatform} onChange={e => setFilterPlatform(e.target.value)} className="input w-auto">
          <option value="">All platforms</option>
          <option value="linkedin">LinkedIn</option>
          <option value="naukri">Naukri</option>
          <option value="indeed">Indeed</option>
          <option value="wellfound">Wellfound</option>
        </select>
        <button
          onClick={() => setShowArchived(!showArchived)}
          className={`flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border transition-colors ${
            showArchived
              ? "border-amber-700 bg-amber-900/20 text-amber-300"
              : "border-zinc-700 bg-zinc-800 text-zinc-400 hover:text-zinc-200"
          }`}
        >
          {showArchived ? <Eye size={13} /> : <EyeOff size={13} />}
          {showArchived ? "Showing all" : "Show archived"}
        </button>
      </div>

      {/* Jobs grid with recency sections */}
      {loading ? (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="card p-5 h-40 animate-pulse bg-zinc-800/50" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="card p-12 text-center">
          <p className="text-zinc-500 mb-4">No jobs found. Try discovering new jobs or enable "Show archived".</p>
        </div>
      ) : (
        <div className="space-y-6">
          {sortedBuckets.map(([bucket, bucketJobs]) => (
            <div key={bucket}>
              <div className="flex items-center gap-3 mb-3">
                <h2 className="text-sm font-semibold text-zinc-400">{RECENCY_LABELS[bucket] || "Other"}</h2>
                <span className="text-xs text-zinc-600">{bucketJobs.length} jobs</span>
                <div className="flex-1 h-px bg-zinc-800" />
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {bucketJobs.map(job => (
                  <JobCard key={job.id} job={job} onUpdate={load}
                    portal={job.source_platform ? portals[job.source_platform] : undefined} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
