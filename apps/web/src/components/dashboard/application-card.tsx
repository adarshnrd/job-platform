"use client";
import { Application } from "@/types";
import { STATUS_CONFIG, PLATFORM_LABELS, formatSalary, scoreColor, timeAgo, cn } from "@/lib/utils";
import { Star, ExternalLink, Zap, BookOpen } from "lucide-react";
import { api } from "@/lib/api";
import toast from "react-hot-toast";
import Link from "next/link";

export function ApplicationCard({ application: app, onUpdate }: { application: Application; onUpdate: () => void }) {
  const status = STATUS_CONFIG[app.status];
  const score = app.match_score;

  const handleStar = async (e: React.MouseEvent) => {
    e.preventDefault();
    try {
      await api.applications.star(app.id);
      onUpdate();
    } catch { toast.error("Failed to update"); }
  };

  const handleApply = async (e: React.MouseEvent) => {
    e.preventDefault();
    try {
      await api.applications.apply(app.id);
      toast.success("Queued for auto-apply!");
      onUpdate();
    } catch (e: any) { toast.error(e.message); }
  };

  return (
    <div className="bg-zinc-800/60 border border-zinc-700/50 rounded-lg p-3 hover:border-zinc-600 transition-colors group">
      {/* Top row */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium truncate">{app.job_title || "Unknown Role"}</p>
          <p className="text-xs text-zinc-400 truncate">{app.job_company}</p>
        </div>
        <div className={cn("score-ring text-xs font-mono flex-shrink-0", scoreColor(score),
          score >= 80 ? "bg-green-900/30" : score >= 60 ? "bg-blue-900/30" : "bg-zinc-800")}>
          {score}
        </div>
      </div>

      {/* Meta */}
      <div className="flex flex-wrap gap-1 mb-2">
        <span className={cn("text-xs px-1.5 py-0.5 rounded", status.bg, status.color)}>{status.label}</span>
        {app.source_platform && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-300">
            {PLATFORM_LABELS[app.source_platform] || app.source_platform}
          </span>
        )}
        {app.is_easy_apply && (
          <span className="text-xs px-1.5 py-0.5 rounded bg-blue-900/40 text-blue-300">Easy Apply</span>
        )}
      </div>

      {/* Salary */}
      {(app.salary_min || app.salary_max) && (
        <p className="text-xs text-zinc-500 mb-2">{formatSalary(app.salary_min, app.salary_max, app.salary_currency)}</p>
      )}

      {/* Actions */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button onClick={handleStar} className={cn("p-1 rounded hover:bg-zinc-700 transition-colors", app.is_starred ? "text-amber-400" : "text-zinc-500")}>
          <Star size={12} fill={app.is_starred ? "currentColor" : "none"} />
        </button>
        {app.status === "matched" && (
          <button onClick={handleApply} className="flex items-center gap-1 text-xs bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 px-2 py-1 rounded transition-colors">
            <Zap size={10} /> Apply
          </button>
        )}
        <Link href={`/interview?app=${app.id}`} className="p-1 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-700 transition-colors">
          <BookOpen size={12} />
        </Link>
        {app.source_url && (
          <a href={app.source_url} target="_blank" rel="noopener noreferrer" className="p-1 rounded text-zinc-500 hover:text-zinc-200 hover:bg-zinc-700 transition-colors">
            <ExternalLink size={12} />
          </a>
        )}
        <span className="ml-auto text-zinc-600 text-xs">{timeAgo(app.created_at)}</span>
      </div>
    </div>
  );
}
