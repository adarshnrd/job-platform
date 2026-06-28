"use client";
import { Application } from "@/types";
import { STATUS_CONFIG, TIER_CONFIG, PLATFORM_LABELS, formatSalary, scoreColor, timeAgo, cn } from "@/lib/utils";
import { Star, ExternalLink, Zap, BookOpen, MapPin, Clock } from "lucide-react";
import { api } from "@/lib/api";
import toast from "react-hot-toast";
import Link from "next/link";

export function JobCard({ job, onUpdate }: { job: Application; onUpdate: () => void }) {
  const score = job.match_score;
  const tier = TIER_CONFIG[job.match_tier];
  const status = STATUS_CONFIG[job.status];

  const handleApply = async () => {
    try {
      await api.applications.apply(job.id);
      toast.success("Application queued!");
      onUpdate();
    } catch (e: any) { toast.error(e.message); }
  };

  const handleScore = async () => {
    toast.loading("Scoring...");
    try {
      const result = await api.jobs.score(job.job_listing_id);
      toast.dismiss();
      toast.success(`Match score: ${result.match_score}%`);
      onUpdate();
    } catch { toast.dismiss(); toast.error("Scoring failed"); }
  };

  return (
    <div className="card p-5 hover:border-zinc-700 transition-colors group">
      {/* Header */}
      <div className="flex items-start gap-3 mb-3">
        {/* Company logo placeholder */}
        <div className="w-10 h-10 rounded-lg bg-zinc-800 flex items-center justify-center text-lg flex-shrink-0 border border-zinc-700">
          {(job.job_company || "?")[0].toUpperCase()}
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold truncate">{job.job_title}</h3>
          <p className="text-sm text-zinc-400">{job.job_company}</p>
        </div>
        <div className={cn("score-ring text-sm font-mono flex-shrink-0", scoreColor(score),
          score >= 80 ? "border-2 border-green-500/50 bg-green-900/20" : score >= 60 ? "border-2 border-blue-500/50 bg-blue-900/20" : "bg-zinc-800")}>
          {score}
        </div>
      </div>

      {/* Badges */}
      <div className="flex flex-wrap gap-1.5 mb-3">
        <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium", tier.color, "bg-zinc-800")}>
          {tier.label}
        </span>
        <span className={cn("text-xs px-2 py-0.5 rounded-full", status.bg, status.color)}>{status.label}</span>
        {job.recency_bucket !== undefined && job.recency_bucket <= 1 && (
          <span className={cn("text-xs px-2 py-0.5 rounded-full font-medium",
            job.recency_bucket === 0
              ? "bg-green-900/30 text-green-300 border border-green-800/50"
              : "bg-blue-900/30 text-blue-300 border border-blue-800/50"
          )}>
            {job.recency_bucket === 0 ? "New" : "2d ago"}
          </span>
        )}
        {job.skill_rescued && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-amber-900/30 text-amber-300 border border-amber-800/50">
            ⚡ Skill: {(job.rescue_skills || []).slice(0, 2).join(", ")}
          </span>
        )}
        {job.source_platform && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-400">
            {PLATFORM_LABELS[job.source_platform]}
          </span>
        )}
        {job.is_easy_apply && (
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-900/30 text-blue-300 border border-blue-800/50">⚡ Easy Apply</span>
        )}
      </div>

      {/* Details */}
      <div className="flex items-center gap-3 text-xs text-zinc-500 mb-3">
        {job.job_location && <span className="flex items-center gap-1"><MapPin size={11} />{job.job_location}</span>}
        {job.job_work_mode && <span className="capitalize">{job.job_work_mode}</span>}
        {(job.salary_min || job.salary_max) && <span>{formatSalary(job.salary_min, job.salary_max, job.salary_currency)}</span>}
        <span className="ml-auto flex items-center gap-1"><Clock size={11} />{timeAgo(job.job_posted_at || job.created_at)}</span>
      </div>

      {/* Skills */}
      {job.job_required_skills && job.job_required_skills.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {job.job_required_skills.slice(0, 5).map(skill => (
            <span key={skill} className={cn("text-xs px-1.5 py-0.5 rounded bg-zinc-800",
              job.skill_gaps?.includes(skill) ? "text-red-400" : "text-zinc-400"
            )}>{skill}</span>
          ))}
          {job.job_required_skills.length > 5 && (
            <span className="text-xs text-zinc-600">+{job.job_required_skills.length - 5}</span>
          )}
        </div>
      )}

      {/* Match summary */}
      {job.match_analysis?.summary && (
        <p className="text-xs text-zinc-500 italic mb-3 line-clamp-2">{job.match_analysis.summary}</p>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 pt-3 border-t border-zinc-800">
        {(job.status === "matched" || job.status === "discovered") && (
          <button onClick={handleApply} className="btn-primary text-xs py-1.5 flex items-center gap-1">
            <Zap size={11} /> Apply Now
          </button>
        )}
        {!job.match_score && (
          <button onClick={handleScore} className="btn-secondary text-xs py-1.5">Score Me</button>
        )}
        <Link href={`/interview?app=${job.id}`} className="btn-ghost text-xs flex items-center gap-1">
          <BookOpen size={11} /> Prep
        </Link>
        <div className="ml-auto flex gap-1">
          {job.source_url && (
            <a href={job.source_url} target="_blank" rel="noopener noreferrer"
              className="p-1.5 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-800 transition-colors">
              <ExternalLink size={13} />
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
