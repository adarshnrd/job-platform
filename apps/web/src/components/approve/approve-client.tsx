"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Application } from "@/types";
import {
  CheckCircle, X, ExternalLink, Building2, MapPin, Zap,
  MousePointerClick, AlertTriangle, Check,
} from "lucide-react";
import toast from "react-hot-toast";
import { ApplyModal } from "@/components/applications/apply-modal";

export function ApproveClient() {
  const [jobs, setJobs] = useState<Application[]>([]);
  const [manualJobs, setManualJobs] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);
  // Assisted-apply modal target (Tier B/C portals — user submits themselves).
  const [assisted, setAssisted] = useState<Application | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [pending, manual] = await Promise.all([
        api.approval.pending(),
        api.approval.manualApply().catch(() => [] as Application[]),
      ]);
      setJobs(pending);
      setManualJobs(manual);
    } catch (e: any) {
      toast.error(e.message || "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleApprove = async (job: Application) => {
    setActing(job.id);
    try {
      const res = await api.approval.approve(job.id);
      if (res.mode === "expired") {
        // Listing is gone — don't let the user start filling anything.
        toast.error(res.message || "This job posting has expired — removed from your queue.", { duration: 6000 });
        setJobs(j => j.filter(x => x.id !== job.id));
        setManualJobs(j => j.filter(x => x.id !== job.id));
      } else if (res.mode === "assisted") {
        // Bot can't submit on this portal — open the review-and-submit flow.
        setAssisted(job);
      } else {
        toast.success(`Queued application to ${job.job_company}!`);
        setJobs(j => j.filter(x => x.id !== job.id));
      }
    } catch (e: any) {
      toast.error(e.message || "Failed to approve");
    } finally {
      setActing(null);
    }
  };

  const handleDismiss = async (id: string, company?: string) => {
    setActing(id);
    try {
      await api.approval.dismiss(id);
      toast.success(`Dismissed ${company || "job"}`);
      setJobs(j => j.filter(x => x.id !== id));
      setManualJobs(j => j.filter(x => x.id !== id));
    } catch (e: any) {
      toast.error(e.message || "Failed to dismiss");
    } finally {
      setActing(null);
    }
  };

  const handleMarkApplied = async (job: Application) => {
    setActing(job.id);
    try {
      await api.approval.markManualApplied(job.id);
      toast.success(`Marked ${job.job_company} as applied`);
      setManualJobs(j => j.filter(x => x.id !== job.id));
    } catch (e: any) {
      toast.error(e.message || "Failed to update");
    } finally {
      setActing(null);
    }
  };

  const scoreColor = (score: number) => {
    if (score >= 75) return "text-amber-400";
    if (score >= 65) return "text-blue-400";
    return "text-zinc-400";
  };

  // Human-readable reason for why the bot couldn't submit.
  const failureLabel = (reason?: string) => {
    if (!reason) return "Automation isn't supported on this portal";
    if (reason.startsWith("No adapter")) return "This portal doesn't support auto-apply";
    if (reason.includes("SESSION_EXPIRED")) return "Portal session expired during apply";
    if (reason.startsWith("Listing expired")) return "Listing looked unavailable to the bot";
    return reason;
  };

  const jobMeta = (job: Application) => (
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
  );

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Approve Jobs</h1>
        <p className="text-sm text-zinc-400 mt-0.5">
          These jobs scored 60–79% — approve to apply, dismiss to skip.
        </p>
      </div>

      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="card p-5 h-28 animate-pulse bg-zinc-800/50" />
          ))}
        </div>
      ) : (
        <>
          {/* ── AI Apply queue ─────────────────────────────────────────── */}
          <section className="space-y-3">
            <div>
              <h2 className="text-sm font-semibold flex items-center gap-2">
                <Zap size={15} className="text-amber-400" /> AI Apply
              </h2>
              <p className="text-xs text-zinc-500 mt-0.5">
                Approve and the bot applies for you — portals without automation open a review-and-submit flow instead.
              </p>
            </div>
            {jobs.length === 0 ? (
              <div className="card p-10 text-center">
                <CheckCircle size={32} className="mx-auto text-zinc-700 mb-3" />
                <p className="text-zinc-400 font-medium">Nothing to review</p>
                <p className="text-sm text-zinc-600 mt-1">
                  Jobs below your auto-apply threshold will appear here for manual approval.
                </p>
              </div>
            ) : (
              <>
                <p className="text-xs text-zinc-500">{jobs.length} job{jobs.length !== 1 ? "s" : ""} awaiting your decision</p>
                {jobs.map(job => (
                  <div key={job.id} className="card p-5 flex items-start gap-4">
                    <div className="flex-none text-center w-12">
                      <span className={`text-xl font-bold ${scoreColor(job.match_score)}`}>
                        {job.match_score}
                      </span>
                      <p className="text-[10px] text-zinc-600 leading-tight">match</p>
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <h3 className="font-semibold text-sm leading-snug">{job.job_title}</h3>
                          {jobMeta(job)}
                        </div>
                        <a href={job.source_url} target="_blank" rel="noreferrer"
                          className="flex-none text-zinc-600 hover:text-zinc-300 transition-colors">
                          <ExternalLink size={14} />
                        </a>
                      </div>

                      {job.match_analysis?.summary && (
                        <p className="text-xs text-zinc-500 mt-2 line-clamp-2">{job.match_analysis.summary}</p>
                      )}

                      {(job.match_analysis as any)?.matched_skills?.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {(job.match_analysis as any).matched_skills.slice(0, 5).map((s: string) => (
                            <span key={s} className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400">
                              {s}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>

                    <div className="flex-none flex flex-col gap-2">
                      <button
                        onClick={() => handleApprove(job)}
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
              </>
            )}
          </section>

          {/* ── Manual Apply ───────────────────────────────────────────── */}
          <section className="space-y-3">
            <div>
              <h2 className="text-sm font-semibold flex items-center gap-2">
                <MousePointerClick size={15} className="text-blue-400" /> Manual Apply
              </h2>
              <p className="text-xs text-zinc-500 mt-0.5">
                The bot couldn&apos;t submit these automatically — open the job link, apply yourself, then mark it done.
              </p>
            </div>
            {manualJobs.length === 0 ? (
              <div className="card p-8 text-center">
                <p className="text-sm text-zinc-600">
                  Nothing here — jobs land here when an automated application attempt fails.
                </p>
              </div>
            ) : (
              <>
                <p className="text-xs text-zinc-500">{manualJobs.length} job{manualJobs.length !== 1 ? "s" : ""} waiting for you</p>
                {manualJobs.map(job => (
                  <div key={job.id} className="card p-5 flex items-start gap-4 border-blue-500/10">
                    <div className="flex-none text-center w-12">
                      <span className={`text-xl font-bold ${scoreColor(job.match_score)}`}>
                        {job.match_score}
                      </span>
                      <p className="text-[10px] text-zinc-600 leading-tight">match</p>
                    </div>

                    <div className="flex-1 min-w-0">
                      <h3 className="font-semibold text-sm leading-snug">{job.job_title}</h3>
                      {jobMeta(job)}
                      <p className="flex items-center gap-1.5 text-xs text-blue-400/90 mt-2">
                        <AlertTriangle size={11} className="flex-none" />
                        {failureLabel(job.failure_reason)}
                      </p>
                    </div>

                    <div className="flex-none flex flex-col gap-2">
                      <a
                        href={job.apply_url || job.source_url}
                        target="_blank" rel="noreferrer"
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-blue-500/10 text-blue-400 hover:bg-blue-500/20 border border-blue-500/30 text-xs font-medium transition-colors"
                      >
                        <ExternalLink size={12} />
                        Open &amp; Apply
                      </a>
                      <button
                        onClick={() => handleMarkApplied(job)}
                        disabled={acting === job.id}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-emerald-500/10 text-emerald-400 hover:bg-emerald-500/20 border border-emerald-500/30 text-xs font-medium transition-colors disabled:opacity-50"
                      >
                        <Check size={12} />
                        I Applied
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
              </>
            )}
          </section>
        </>
      )}

      {/* Assisted-apply flow for Tier B/C portals */}
      {assisted && (
        <ApplyModal
          appId={assisted.id}
          jobTitle={assisted.job_title || ""}
          jobCompany={assisted.job_company || ""}
          onClose={() => setAssisted(null)}
          onUpdated={load}
        />
      )}
    </div>
  );
}
