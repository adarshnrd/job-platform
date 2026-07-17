"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Application, PortalCapability } from "@/types";
import { PLATFORM_LABELS } from "@/lib/utils";
import { JobCard } from "./job-card";
import { Search, Eye, EyeOff, MapPin, X } from "lucide-react";
import toast from "react-hot-toast";

const RECENCY_LABELS: Record<number, string> = {
  0: "Posted Today",
  1: "Posted 2 Days Ago",
  2: "Posted This Week",
  3: "Older Posts",
};

// "Max experience required" choices — value is sent as ?experience=N and the
// API keeps jobs with min_experience <= N (unspecified jobs stay visible).
const EXPERIENCE_OPTIONS: { value: string; label: string }[] = [
  { value: "0", label: "Fresher only" },
  { value: "1", label: "≤ 1 yr required" },
  { value: "2", label: "≤ 2 yrs required" },
  { value: "3", label: "≤ 3 yrs required" },
  { value: "5", label: "≤ 5 yrs required" },
  { value: "8", label: "≤ 8 yrs required" },
  { value: "10", label: "≤ 10 yrs required" },
];

const JOB_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "full_time", label: "Full-time" },
  { value: "part_time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "freelance", label: "Freelance" },
  { value: "internship", label: "Internship" },
];

const POSTED_OPTIONS: { value: string; label: string }[] = [
  { value: "1", label: "Last 24 hours" },
  { value: "3", label: "Last 3 days" },
  { value: "7", label: "Last week" },
  { value: "14", label: "Last 2 weeks" },
];

// Platforms surfaced in the filter dropdown (labels come from PLATFORM_LABELS).
const FILTER_PLATFORMS = [
  "linkedin", "naukri", "indeed", "wellfound", "company_portal",
  "remoteok", "remotive", "timesjobs", "hirist", "iimjobs",
  "shine", "themuse", "careerjet", "jobicy", "himalayas",
] as const;

export function JobsClient() {
  const [jobs, setJobs] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filterPlatform, setFilterPlatform] = useState("");
  const [filterMode, setFilterMode] = useState("");
  const [filterTier, setFilterTier] = useState("");
  const [filterExperience, setFilterExperience] = useState("");
  const [filterJobType, setFilterJobType] = useState("");
  const [filterPosted, setFilterPosted] = useState("");
  const [locationInput, setLocationInput] = useState("");
  const [filterLocation, setFilterLocation] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [portals, setPortals] = useState<Record<string, PortalCapability>>({});

  // Debounce the location text so typing doesn't fire a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => setFilterLocation(locationInput.trim()), 400);
    return () => clearTimeout(t);
  }, [locationInput]);

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
      if (filterExperience) params.experience = filterExperience;
      if (filterJobType) params.job_type = filterJobType;
      if (filterPosted) params.posted_within_days = filterPosted;
      if (filterLocation) params.location = filterLocation;
      if (showArchived) params.show_archived = "true";
      const data = await api.jobs.list(params);
      setJobs(data.data || data.matched || []);
    } catch (e: any) {
      toast.error(e.message || "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [filterPlatform, filterMode, filterExperience, filterJobType, filterPosted, filterLocation, showArchived]);

  const hasActiveFilters = !!(filterPlatform || filterMode || filterTier || filterExperience
    || filterJobType || filterPosted || locationInput || search);

  const clearFilters = () => {
    setSearch(""); setFilterPlatform(""); setFilterMode(""); setFilterTier("");
    setFilterExperience(""); setFilterJobType(""); setFilterPosted("");
    setLocationInput(""); setFilterLocation("");
  };

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

      {/* Filters — experience first, it's the primary criterion */}
      <div className="flex gap-3 flex-wrap">
        <div className="relative flex-1 min-w-64">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search title or company..." className="input pl-9" />
        </div>
        <select value={filterExperience} onChange={e => setFilterExperience(e.target.value)}
          title="Show jobs whose required experience is at most this (jobs without a stated requirement stay visible)"
          className="input w-auto">
          <option value="">Any experience</option>
          {EXPERIENCE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <div className="relative w-44">
          <MapPin size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" />
          <input value={locationInput} onChange={e => setLocationInput(e.target.value)} placeholder="Location..." className="input pl-9" />
        </div>
        <select value={filterJobType} onChange={e => setFilterJobType(e.target.value)} className="input w-auto">
          <option value="">All job types</option>
          {JOB_TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <select value={filterPosted} onChange={e => setFilterPosted(e.target.value)} className="input w-auto">
          <option value="">Any time</option>
          {POSTED_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
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
          {FILTER_PLATFORMS.map(p => <option key={p} value={p}>{PLATFORM_LABELS[p]}</option>)}
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
        {hasActiveFilters && (
          <button onClick={clearFilters}
            className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-zinc-700 bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors">
            <X size={13} /> Clear filters
          </button>
        )}
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
