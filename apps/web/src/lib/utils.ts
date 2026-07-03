import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { ApplicationStatus, MatchTier, Platform } from "@/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatSalary(min?: number, max?: number, currency = "INR"): string {
  if (!min && !max) return "Salary not disclosed";
  const fmt = (n: number) => currency === "INR" ? `₹${(n / 100000).toFixed(1)}L` : `$${Math.round(n / 1000)}K`;
  if (min && max) return `${fmt(min)} – ${fmt(max)}`;
  if (min) return `${fmt(min)}+`;
  return `Up to ${fmt(max!)}`;
}

export function formatDate(dateStr?: string): string {
  if (!dateStr) return "";
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" }).format(new Date(dateStr));
}

export function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime();
  const hours = Math.floor(diff / 3600000);
  if (hours < 1) return "Just now";
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return `${Math.floor(days / 30)}mo ago`;
}

export const STATUS_CONFIG: Record<ApplicationStatus, { label: string; color: string; bg: string }> = {
  discovered:          { label: "Discovered",        color: "text-zinc-400",    bg: "bg-zinc-800" },
  matched:             { label: "Matched",            color: "text-blue-400",    bg: "bg-blue-900/40" },
  queued:              { label: "Queued",             color: "text-amber-400",   bg: "bg-amber-900/40" },
  applying:            { label: "Applying...",        color: "text-amber-400",   bg: "bg-amber-900/40" },
  needs_input:         { label: "Needs Answer",        color: "text-amber-300",   bg: "bg-amber-900/40" },
  applied:             { label: "Applied",            color: "text-green-400",   bg: "bg-green-900/40" },
  under_review:        { label: "Under Review",       color: "text-cyan-400",    bg: "bg-cyan-900/40" },
  assessment:          { label: "Assessment",         color: "text-purple-400",  bg: "bg-purple-900/40" },
  interview_scheduled: { label: "Interview",          color: "text-violet-400",  bg: "bg-violet-900/40" },
  technical_round:     { label: "Technical Round",   color: "text-violet-400",  bg: "bg-violet-900/40" },
  hr_round:            { label: "HR Round",           color: "text-violet-400",  bg: "bg-violet-900/40" },
  offer_received:      { label: "Offer! 🎉",          color: "text-emerald-400", bg: "bg-emerald-900/40" },
  rejected:            { label: "Rejected",           color: "text-red-400",     bg: "bg-red-900/40" },
  withdrawn:           { label: "Withdrawn",          color: "text-zinc-500",    bg: "bg-zinc-800" },
  accepted:            { label: "Accepted ✓",         color: "text-emerald-400", bg: "bg-emerald-900/40" },
};

export const TIER_CONFIG: Record<MatchTier, { label: string; color: string; description: string }> = {
  auto_apply:  { label: "Auto Apply",   color: "text-green-400",  description: "80%+ match — auto-applying" },
  recommended: { label: "Recommended",  color: "text-blue-400",   description: "60–79% match" },
  watchlist:   { label: "Watchlist",    color: "text-amber-400",  description: "50–59% match" },
  archived:    { label: "Archived",     color: "text-zinc-500",   description: "Below 50% match" },
};

export const PLATFORM_LABELS: Record<Platform, string> = {
  linkedin: "LinkedIn", naukri: "Naukri", indeed: "Indeed", wellfound: "Wellfound",
  hirist: "Hirist", instahyre: "Instahyre", cutshort: "Cutshort", glassdoor: "Glassdoor",
  foundit: "Foundit", remoteok: "RemoteOK", weworkremotely: "We Work Remotely",
  iimjobs: "iimjobs", timesjobs: "TimesJobs", shine: "Shine",
  freshersworld: "Freshersworld", ycombinator: "Y Combinator",
  company_portal: "Company Portal", other: "Other",
};

export function scoreColor(score: number): string {
  if (score >= 80) return "text-green-400";
  if (score >= 60) return "text-blue-400";
  if (score >= 50) return "text-amber-400";
  return "text-red-400";
}
