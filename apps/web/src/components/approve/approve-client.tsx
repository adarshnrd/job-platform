"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { CheckCircle, X, ExternalLink, Building2, MapPin, Zap } from "lucide-react";
import toast from "react-hot-toast";

export function ApproveClient() {
  const [jobs, setJobs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.approval.pending();
      setJobs(data);
    } catch (e: any) {
      toast.error(e.message || "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleApprove = async (id: string, title: string, company: string) => {
    setActing(id);
    try {
      await api.approval.approve(id);
      toast.success(`Queued application to ${company}!`);
      setJobs(j => j.filter(x => x.id !== id));
    } catch (e: any) {
      toast.error(e.message || "Failed to approve");
    } finally {
      setActing(null);
    }
  };

  const handleDismiss = async (id: string, company: string) => {
    setActing(id);
    try {
      await api.approval.dismiss(id);
      toast.success(`Dismissed ${company}`);
      setJobs(j => j.filter(x => x.id !== id));
    } catch (e: any) {
      toast.error(e.message || "Failed to dismiss");
    } finally {
      setActing(null);
    }
  };

  const scoreColor = (score: number) => {
    if (score >= 75) return "text-amber-400";
    if (score >= 65) return "text-blue-400";
    return "text-zinc-400";
  };

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-2xl font-bold">Approve Jobs</h1>
        <p className="text-sm text-zinc-400 mt-0.5">
          These jobs scored 60–79% — approve to auto-apply, dismiss to skip.
        </p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-5 h-28 animate-pulse bg-zinc-800/50" />
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <div className="card p-12 text-center">
          <CheckCircle size={40} className="mx-auto text-zinc-700 mb-4" />
          <p className="text-zinc-400 font-medium">Nothing to review</p>
          <p className="text-sm text-zinc-600 mt-1">
            Jobs below your auto-apply threshold will appear here for manual approval.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-zinc-500">{jobs.length} job{jobs.length !== 1 ? "s" : ""} awaiting your decision</p>
          {jobs.map(job => (
            <div key={job.id} className="card p-5 flex items-start gap-4">
              {/* Score badge */}
              <div className="flex-none text-center w-12">
                <span className={`text-xl font-bold ${scoreColor(job.match_score)}`}>
                  {job.match_score}
                </span>
                <p className="text-[10px] text-zinc-600 leading-tight">match</p>
              </div>

              {/* Job info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <h3 className="font-semibold text-sm leading-snug">{job.job_title}</h3>
                    <div className="flex items-center gap-3 mt-1 text-xs text-zinc-400">
                      <span className="flex items-center gap-1">
                        <Building2 size={11} />
                        {job.job_company}
                      </span>
                      {job.job_location && (
                        <span className="flex items-center gap-1">
                          <MapPin size={11} />
                          {job.job_location}
                        </span>
                      )}
                      <span className="capitalize text-zinc-500">{job.source_platform}</span>
                    </div>
                  </div>
                  <a href={job.source_url} target="_blank" rel="noreferrer"
                    className="flex-none text-zinc-600 hover:text-zinc-300 transition-colors">
                    <ExternalLink size={14} />
                  </a>
                </div>

                {/* Match summary */}
                {job.match_analysis?.summary && (
                  <p className="text-xs text-zinc-500 mt-2 line-clamp-2">{job.match_analysis.summary}</p>
                )}

                {/* Matched skills */}
                {job.match_analysis?.matched_skills?.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {job.match_analysis.matched_skills.slice(0, 5).map((s: string) => (
                      <span key={s} className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400">
                        {s}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Action buttons */}
              <div className="flex-none flex flex-col gap-2">
                <button
                  onClick={() => handleApprove(job.id, job.job_title, job.job_company)}
                  disabled={acting === job.id}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 border border-amber-500/30 text-xs font-medium transition-colors disabled:opacity-50"
                >
                  <Zap size={12} />
                  Apply
                </button>
                <button
                  onClick={() => handleDismiss(job.id, job.job_company)}
                  disabled={acting === job.id}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 border border-zinc-700 text-xs font-medium transition-colors disabled:opacity-50"
                >
                  <X size={12} />
                  Skip
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
