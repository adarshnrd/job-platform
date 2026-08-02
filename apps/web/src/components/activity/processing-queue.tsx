"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DiscoveryQueue } from "@/types";
import { AlertTriangle, CheckCircle2, Layers, Loader2, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";

/** Stage labels in pipeline order. Anything counted here is already saved to the
 *  database — these stages only add AI analysis on top of a stored job. */
const STAGE_LABELS: Record<string, string> = {
  scraped: "Awaiting analysis",
  parsed: "Awaiting enrichment",
  enriched: "Awaiting scoring",
  scored: "Finishing up",
};

export function ProcessingQueuePanel({ pollMs = 15000 }: { pollMs?: number }) {
  const [queue, setQueue] = useState<DiscoveryQueue | null>(null);
  const [retrying, setRetrying] = useState(false);

  const load = useCallback(async () => {
    try {
      setQueue(await api.discovery.queue());
    } catch {
      /* non-fatal: the panel is diagnostic, not load-bearing */
    }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, pollMs);
    return () => clearInterval(t);
  }, [load, pollMs]);

  const retry = async () => {
    setRetrying(true);
    try {
      const res = await api.discovery.retryQueue();
      toast.success(res.message);
      load();
    } catch (e: any) {
      toast.error(e.message || "Retry failed");
    } finally {
      setRetrying(false);
    }
  };

  if (!queue?.available) return null;

  const { totals } = queue;
  const inFlight = totals.pending + totals.processing;
  if (!inFlight && !totals.failed) return null;

  const stageRows = Object.entries(queue.stages)
    .filter(([stage]) => stage in STAGE_LABELS)
    .map(([stage, counts]) => ({
      stage,
      label: STAGE_LABELS[stage],
      waiting: counts.pending + counts.processing,
      failed: counts.failed,
    }))
    .filter((r) => r.waiting > 0 || r.failed > 0);

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Layers size={15} className="text-amber-400" /> Processing queue
          <span className="text-zinc-500 font-normal">
            — saved jobs still being analysed
          </span>
        </h2>
        {totals.failed > 0 && (
          <button onClick={retry} disabled={retrying}
            className="text-xs flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-zinc-700 text-zinc-300 hover:text-zinc-100 hover:border-zinc-600 transition-colors disabled:opacity-50">
            {retrying ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
            Retry {totals.failed} failed
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Waiting", value: totals.pending, tone: "text-zinc-100" },
          { label: "In progress", value: totals.processing, tone: "text-amber-400" },
          { label: "Needs retry", value: totals.failed, tone: totals.failed ? "text-red-400" : "text-zinc-100" },
          { label: "Completed", value: totals.done, tone: "text-emerald-400" },
        ].map((c) => (
          <div key={c.label} className="bg-zinc-900/70 border border-zinc-800 rounded-lg px-3 py-2.5">
            <div className={cn("text-lg font-bold", c.tone)}>{c.value}</div>
            <div className="text-[11px] text-zinc-500">{c.label}</div>
          </div>
        ))}
      </div>

      {stageRows.length > 0 && (
        <div className="space-y-1.5">
          {stageRows.map((r) => (
            <div key={r.stage} className="flex items-center justify-between text-xs px-3 py-2 rounded-lg bg-zinc-900/50 border border-zinc-800">
              <span className="text-zinc-400">{r.label}</span>
              <span className="flex items-center gap-3">
                {r.waiting > 0 && <span className="text-zinc-200 font-medium">{r.waiting} queued</span>}
                {r.failed > 0 && (
                  <span className="text-red-400 flex items-center gap-1">
                    <AlertTriangle size={11} /> {r.failed} failed
                  </span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {queue.failed.length > 0 && (
        <div className="space-y-1">
          <div className="text-[11px] text-zinc-500">Recent failures</div>
          {queue.failed.slice(0, 5).map((f) => (
            <div key={f.id} className="text-xs px-3 py-2 rounded-lg bg-red-500/5 border border-red-500/15">
              <div className="text-zinc-200">
                {f.job_title || "Untitled role"}
                {f.job_company && <span className="text-zinc-500"> · {f.job_company}</span>}
                <span className="text-zinc-600"> · {f.stage} · {f.attempts} attempt{f.attempts === 1 ? "" : "s"}</span>
              </div>
              {f.last_error && <div className="text-red-400/80 mt-0.5 font-mono text-[10.5px]">{f.last_error}</div>}
            </div>
          ))}
        </div>
      )}

      <p className="text-[11px] text-zinc-500 flex items-center gap-1.5">
        <CheckCircle2 size={11} className="text-emerald-500 shrink-0" />
        Every job here is already stored. Analysis resumes automatically — a failed
        stage never loses the job itself.
      </p>
    </div>
  );
}
