"use client";
import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { createClient } from "@/lib/supabase/client";
import { KanbanColumn, PipelineStats } from "@/types";
import { PipelineKanban } from "./pipeline-kanban";
import { StatsRow } from "./stats-row";
import { Zap, RefreshCw, Globe, MapPin, FileSpreadsheet } from "lucide-react";
import toast from "react-hot-toast";
import { SessionBanner } from "./session-banner";
import { PendingQuestionsBanner } from "./pending-questions-banner";

type Region = "india" | "global";

export function DashboardClient({ user }: { user: any }) {
  const [pipeline, setPipeline] = useState<KanbanColumn[]>([]);
  const [stats, setStats] = useState<PipelineStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [downloadingTracker, setDownloadingTracker] = useState(false);
  const [region, setRegion] = useState<Region>("india");

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.applications.pipeline();
      setPipeline(data.pipeline || []);
      setStats(data.stats || null);
    } catch (e: any) {
      toast.error(e.message || "Failed to load pipeline");
    } finally {
      setLoading(false);
    }
  };

  const triggerDiscovery = async () => {
    setDiscovering(true);
    try {
      await api.jobs.discover({
        platforms: user?.preferred_platforms || ["linkedin", "naukri", "indeed"],
        region,
      });
      toast.success(
        region === "india"
          ? "Searching Indian job market — you'll be notified of new matches."
          : "Searching globally — you'll be notified of new matches."
      );
    } catch (e: any) {
      toast.error(e.message || "Discovery failed");
    } finally {
      setDiscovering(false);
    }
  };

  const downloadTracker = useCallback(async () => {
    setDownloadingTracker(true);
    try {
      const supabase = createClient();
      const { data: { session } } = await supabase.auth.getSession();
      if (!session?.access_token) throw new Error("Not authenticated");
      const res = await fetch(api.export.jobTrackerUrl(), {
        headers: { Authorization: `Bearer ${session.access_token}` },
      });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `job_tracker_${new Date().toISOString().slice(0, 10)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
      toast.success("Job Tracker downloaded");
    } catch (e: any) {
      toast.error(e.message || "Download failed");
    } finally {
      setDownloadingTracker(false);
    }
  }, []);

  useEffect(() => { load(); }, []);

  return (
    <div className="space-y-6">
      {/* Session expiry banner */}
      <SessionBanner />
      {/* Pending Answer Bank questions */}
      <PendingQuestionsBanner />

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Job Pipeline</h1>
          <p className="text-sm text-zinc-400 mt-0.5">
            {user?.auto_apply_enabled
              ? `Auto-applying at ${user?.auto_apply_threshold}%+ match`
              : "Manual apply mode"}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Region toggle */}
          <div className="flex items-center rounded-lg border border-zinc-700 bg-zinc-900 p-0.5">
            <button
              onClick={() => setRegion("india")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                region === "india" ? "bg-amber-500 text-black" : "text-zinc-400 hover:text-zinc-100"
              }`}
              title="Search the Indian job market"
            >
              <MapPin size={13} />
              India
            </button>
            <button
              onClick={() => setRegion("global")}
              className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                region === "global" ? "bg-amber-500 text-black" : "text-zinc-400 hover:text-zinc-100"
              }`}
              title="Search globally (remote + worldwide)"
            >
              <Globe size={13} />
              Global
            </button>
          </div>

          <button
            onClick={downloadTracker}
            disabled={downloadingTracker}
            className="btn-secondary flex items-center gap-2"
            title="Download Job Tracker spreadsheet (all jobs with 50%+ match)"
          >
            <FileSpreadsheet size={14} />
            {downloadingTracker ? "Downloading..." : "Job Tracker"}
          </button>
          <button onClick={load} disabled={loading} className="btn-secondary flex items-center gap-2">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          <button onClick={triggerDiscovery} disabled={discovering} className="btn-primary flex items-center gap-2">
            <Zap size={14} />
            {discovering ? "Discovering..." : "Discover Jobs"}
          </button>
        </div>
      </div>

      {/* Stats */}
      {stats && <StatsRow stats={stats} />}

      {/* Kanban board */}
      {loading ? (
        <div className="flex items-center justify-center h-64 text-zinc-500">Loading pipeline...</div>
      ) : (
        <PipelineKanban columns={pipeline} onUpdate={load} />
      )}
    </div>
  );
}
