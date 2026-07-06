"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { SourceHealth } from "@/types";
import { AlertTriangle, CheckCircle2, HeartPulse, HelpCircle, Loader2, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtMs, timeAgo } from "./format";

const FLAG_LABELS: Record<string, string> = {
  consecutive_errors: "Failing — last runs errored",
  yield_drop: "Degraded — yield dropped >70% vs baseline",
  insufficient_data: "Not enough runs yet",
};

function Sparkline({ daily }: { daily: SourceHealth["daily"] }) {
  const max = Math.max(1, ...daily.map((d) => d.jobs_seen));
  const w = 6;
  const gap = 2;
  const h = 32;
  return (
    <svg width={daily.length * (w + gap)} height={h} className="block">
      {daily.map((d, i) => {
        const bh = d.runs === 0 ? 0 : Math.max(2, Math.round((d.jobs_seen / max) * (h - 2)));
        return (
          <g key={d.day}>
            <title>{`${d.day}: ${d.jobs_seen} jobs, ${d.runs} run(s)${d.errors ? `, ${d.errors} error(s)` : ""}`}</title>
            {d.runs === 0 ? (
              <circle cx={i * (w + gap) + w / 2} cy={h - 1.5} r={1} className="fill-zinc-800" />
            ) : (
              <rect
                x={i * (w + gap)} y={h - bh} width={w} height={bh} rx={1}
                className={d.errors > 0 && d.jobs_seen === 0 ? "fill-red-500/70" : d.errors > 0 ? "fill-amber-500/70" : "fill-emerald-500/60"}
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}

export function SourceHealthPanel() {
  const [days, setDays] = useState(14);
  const [data, setData] = useState<SourceHealth[] | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await api.telemetry.sourceHealth(days);
      setData(r.sources);
    } catch {
      setData([]);
    }
  }, [days]);

  useEffect(() => {
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, [load]);

  const flaggedCount = (data || []).filter((s) => s.flagged).length;

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <HeartPulse size={15} className="text-amber-400" /> Scraper health
          {data && (
            flaggedCount > 0 ? (
              <span className="text-red-400 font-normal">— {flaggedCount} source{flaggedCount > 1 ? "s" : ""} degraded</span>
            ) : (
              <span className="text-zinc-500 font-normal">— all sources healthy</span>
            )
          )}
        </h2>
        <div className="flex rounded-lg border border-zinc-800 overflow-hidden">
          {[7, 14, 30].map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={cn(
                "px-2.5 py-1.5 text-xs transition-colors",
                days === d ? "bg-zinc-800 text-zinc-100 font-medium" : "bg-zinc-900 text-zinc-500 hover:text-zinc-200"
              )}>
              {d}d
            </button>
          ))}
        </div>
      </div>

      {data === null ? (
        <div className="py-8 flex items-center justify-center text-zinc-500">
          <Loader2 size={16} className="animate-spin mr-2" /> Loading health data…
        </div>
      ) : data.length === 0 ? (
        <div className="text-sm text-zinc-500 py-6 text-center">
          No source data yet — run a discovery and per-scraper health will build up here.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {data.map((s) => (
            <div key={s.source}
              className={cn(
                "rounded-lg border p-3.5 space-y-2.5",
                s.flagged ? "border-red-500/40 bg-red-500/5" : "border-zinc-800 bg-zinc-900/50"
              )}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-zinc-100 capitalize">{s.source}</span>
                {s.flagged ? (
                  <span className="inline-flex items-center gap-1 text-[11px] text-red-400">
                    <AlertTriangle size={12} /> {s.flag_reason === "consecutive_errors" ? "failing" : "degraded"}
                  </span>
                ) : s.flag_reason === "insufficient_data" ? (
                  <span className="inline-flex items-center gap-1 text-[11px] text-zinc-500">
                    <HelpCircle size={12} /> warming up
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-[11px] text-emerald-400">
                    <CheckCircle2 size={12} /> healthy
                  </span>
                )}
              </div>

              <Sparkline daily={s.daily} />

              <div className="flex items-center justify-between text-[11px] text-zinc-500">
                <span>
                  {s.runs} run{s.runs !== 1 ? "s" : ""} · {Math.round((s.success_rate ?? 0) * 100)}% ok
                  {s.baseline_yield > 0 && ` · ~${Math.round(s.baseline_yield)}/run`}
                </span>
                <span title={s.latest.finished_at}>{timeAgo(s.latest.finished_at)}</span>
              </div>

              <div className="text-[11px]">
                {s.latest.status === "error" ? (
                  <span className="text-red-400 inline-flex items-center gap-1">
                    <XCircle size={11} /> last run: {s.latest.error || "failed"}
                  </span>
                ) : (
                  <span className="text-zinc-400">
                    last run: {s.latest.jobs_seen} seen · {s.latest.jobs_found} new · {fmtMs(s.latest.duration_ms)}
                  </span>
                )}
              </div>

              {s.flagged && FLAG_LABELS[s.flag_reason || ""] && (
                <div className="text-[11px] text-red-400/80">{FLAG_LABELS[s.flag_reason || ""]}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
