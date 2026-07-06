"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { DiscoveryRun, TelemetryRun } from "@/types";
import { CheckCircle2, ChevronDown, ChevronRight, Clock, Loader2, Search, Send, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { duration, fmtMs, timeAgo } from "./format";

/** Older runs live only in the JSON history file — map them into ledger shape. */
function legacyToLedger(run: DiscoveryRun): TelemetryRun {
  return {
    run_id: run.run_id,
    kind: "discovery",
    user_id: run.user_id,
    trigger: run.trigger,
    region: run.region,
    status: run.status,
    started_at: run.started_at,
    finished_at: run.finished_at,
    duration_ms: null,
    counts: run.counts as unknown as Record<string, number>,
    error: run.error,
    sources: Object.entries(run.sources || {}).map(([source, s]) => ({
      source,
      status: s.status,
      jobs_found: s.jobs_found,
      jobs_seen: s.jobs_seen ?? 0,
      duration_ms: s.duration_ms ?? 0,
      error: s.error,
      finished_at: run.finished_at ?? run.started_at,
    })),
  };
}

export function RunLedger() {
  const [runs, setRuns] = useState<TelemetryRun[] | null>(null);
  const [kind, setKind] = useState<"all" | "discovery" | "apply">("all");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [ledger, legacy] = await Promise.all([
        api.telemetry.runs(kind === "all" ? undefined : kind, 50),
        kind === "apply"
          ? Promise.resolve({ runs: [] as DiscoveryRun[] })
          : api.discovery.runs().catch(() => ({ runs: [] as DiscoveryRun[] })),
      ]);
      const seen = new Set(ledger.runs.map((r) => r.run_id));
      const merged = [
        ...ledger.runs,
        ...legacy.runs.filter((r) => !seen.has(r.run_id) && r.status !== "running").map(legacyToLedger),
      ].sort((a, b) => b.started_at.localeCompare(a.started_at));
      setRuns(merged);
    } catch {
      setRuns([]);
    }
  }, [kind]);

  useEffect(() => {
    load();
    const iv = setInterval(load, 15000);
    return () => clearInterval(iv);
  }, [load]);

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Clock size={15} className="text-amber-400" /> Run ledger
        </h2>
        <div className="flex rounded-lg border border-zinc-800 overflow-hidden">
          {(["all", "discovery", "apply"] as const).map((k) => (
            <button key={k} onClick={() => setKind(k)}
              className={cn(
                "px-2.5 py-1.5 text-xs capitalize transition-colors",
                kind === k ? "bg-zinc-800 text-zinc-100 font-medium" : "bg-zinc-900 text-zinc-500 hover:text-zinc-200"
              )}>
              {k}
            </button>
          ))}
        </div>
      </div>

      {runs === null ? (
        <div className="py-8 flex items-center justify-center text-zinc-500">
          <Loader2 size={16} className="animate-spin mr-2" /> Loading ledger…
        </div>
      ) : runs.length === 0 ? (
        <div className="text-sm text-zinc-500 py-6 text-center">
          No runs recorded yet — discovery and apply runs will appear here as they happen.
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-zinc-500 border-b border-zinc-800">
              <th className="w-6" />
              <th className="text-left py-2 font-medium">Started</th>
              <th className="text-left py-2 font-medium">Kind</th>
              <th className="text-left py-2 font-medium">Trigger</th>
              <th className="text-right py-2 font-medium">Duration</th>
              <th className="text-right py-2 font-medium">Results</th>
              <th className="text-right py-2 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60">
            {runs.map((r) => {
              const isOpen = expanded === r.run_id;
              const hasDetail = r.sources.length > 0 || !!r.error;
              return [
                <tr key={r.run_id}
                  className={cn("text-zinc-300", hasDetail && "cursor-pointer hover:bg-zinc-900/50")}
                  onClick={() => hasDetail && setExpanded(isOpen ? null : r.run_id)}>
                  <td className="py-2.5 text-zinc-600">
                    {hasDetail && (isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />)}
                  </td>
                  <td className="py-2.5" title={new Date(r.started_at).toLocaleString()}>
                    {timeAgo(r.started_at)}
                  </td>
                  <td className="py-2.5">
                    <span className={cn(
                      "inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded border",
                      r.kind === "discovery"
                        ? "border-sky-500/30 text-sky-400 bg-sky-500/5"
                        : "border-violet-500/30 text-violet-400 bg-violet-500/5"
                    )}>
                      {r.kind === "discovery" ? <Search size={11} /> : <Send size={11} />}
                      {r.kind}
                    </span>
                  </td>
                  <td className="py-2.5 capitalize text-zinc-400">
                    {r.trigger || "—"}{r.region ? ` · ${r.region}` : ""}
                  </td>
                  <td className="py-2.5 text-right text-zinc-400">
                    {r.duration_ms != null ? fmtMs(r.duration_ms) : duration(r.started_at, r.finished_at)}
                  </td>
                  <td className="py-2.5 text-right text-zinc-400">
                    {r.kind === "discovery"
                      ? `${r.counts.scraped ?? 0} found · ${r.counts.matched ?? 0} matched`
                      : `${r.counts.applied ?? 0}/${r.counts.attempted ?? 0} applied`}
                  </td>
                  <td className="py-2.5 text-right">
                    {r.status === "failed" ? (
                      <span className="inline-flex items-center gap-1 text-red-400"><XCircle size={12} /> failed</span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-emerald-400"><CheckCircle2 size={12} /> {r.status}</span>
                    )}
                  </td>
                </tr>,
                isOpen && (
                  <tr key={`${r.run_id}-detail`}>
                    <td colSpan={7} className="pb-3">
                      <div className="bg-zinc-900/60 border border-zinc-800 rounded-lg p-3 space-y-2">
                        {r.error && <div className="text-xs text-red-400">{r.error}</div>}
                        {r.sources.length > 0 ? (
                          <div className="flex flex-wrap gap-1.5">
                            {r.sources.map((s) => (
                              <span key={s.source} title={s.error || undefined}
                                className={cn(
                                  "inline-flex items-center gap-1.5 px-2 py-1 rounded text-[11px] border",
                                  s.status === "error"
                                    ? "border-red-500/30 text-red-400 bg-red-500/5"
                                    : "border-zinc-800 text-zinc-300 bg-zinc-900"
                                )}>
                                <span className="font-medium">{s.source}</span>
                                {s.status === "error" ? (
                                  <span>failed</span>
                                ) : (
                                  <span className="text-zinc-500">
                                    {s.jobs_seen} seen · {s.jobs_found} new · {fmtMs(s.duration_ms)}
                                  </span>
                                )}
                              </span>
                            ))}
                          </div>
                        ) : (
                          <div className="text-xs text-zinc-500">
                            {Object.entries(r.counts).map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ")}
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ),
              ];
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
