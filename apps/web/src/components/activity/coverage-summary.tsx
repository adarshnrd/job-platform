"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CoverageSource, CoverageSummary, SourceScheduling } from "@/types";
import { Boxes, Loader2, Radar } from "lucide-react";
import { cn } from "@/lib/utils";

const SCHED_META: Record<SourceScheduling, { label: string; cls: string }> = {
  running:      { label: "Running",     cls: "border-emerald-500/40 text-emerald-400 bg-emerald-500/5" },
  probing:      { label: "Probing",     cls: "border-sky-500/40 text-sky-400 bg-sky-500/5" },
  backed_off:   { label: "Backed off",  cls: "border-red-500/40 text-red-400 bg-red-500/5" },
  dormant:      { label: "Needs key",   cls: "border-amber-500/40 text-amber-400 bg-amber-500/5" },
  c_tier:       { label: "Display only", cls: "border-zinc-700 text-zinc-500 bg-zinc-900" },
  other_region: { label: "Other region", cls: "border-zinc-800 text-zinc-600 bg-zinc-900/50" },
};

const KIND_LABEL: Record<CoverageSource["kind"], string> = { ats: "ATS", api: "API", browser: "Browser" };

export function CoverageSummaryPanel() {
  const [data, setData] = useState<CoverageSummary | null>(null);

  const load = useCallback(async () => {
    try { setData(await api.telemetry.coverage(14)); } catch { /* keep last */ }
  }, []);
  useEffect(() => {
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, [load]);

  if (!data) {
    return (
      <div className="card p-6 flex items-center justify-center text-zinc-500">
        <Loader2 size={16} className="animate-spin mr-2" /> Loading coverage…
      </div>
    );
  }

  const t = data.totals;
  // Show the sources that matter first: running (by contribution), then the rest.
  const order: SourceScheduling[] = ["running", "probing", "backed_off", "dormant", "c_tier", "other_region"];
  const sorted = [...data.sources].sort((a, b) =>
    order.indexOf(a.scheduling) - order.indexOf(b.scheduling) || b.jobs_found - a.jobs_found
  );
  const maxJobs = Math.max(1, ...data.sources.map((s) => s.jobs_found));

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Boxes size={15} className="text-amber-400" /> Source coverage
          <span className="text-zinc-500 font-normal">— {t.active} of {t.registered} active in {data.region}</span>
        </h2>
        {data.next_run_is_probe && (
          <span className="inline-flex items-center gap-1.5 text-[11px] text-sky-400 border border-sky-500/40 bg-sky-500/5 rounded-full px-2 py-0.5">
            <Radar size={12} /> next run probes backed-off sources
          </span>
        )}
      </div>

      {/* Totals */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        {[
          { label: "Active", value: t.active, cls: "text-emerald-400" },
          { label: "Backed off", value: t.backed_off, cls: t.backed_off ? "text-red-400" : "text-zinc-300" },
          { label: "Probing", value: t.probing, cls: "text-sky-400" },
          { label: "Needs key", value: t.dormant, cls: t.dormant ? "text-amber-400" : "text-zinc-300" },
          { label: "Display only", value: t.c_tier, cls: "text-zinc-400" },
          { label: "Flagged", value: t.flagged, cls: t.flagged ? "text-red-400" : "text-zinc-300" },
        ].map((c) => (
          <div key={c.label} className="bg-zinc-900/70 border border-zinc-800 rounded-lg px-3 py-2">
            <div className={cn("text-lg font-bold", c.cls)}>{c.value}</div>
            <div className="text-[10px] text-zinc-500">{c.label}</div>
          </div>
        ))}
      </div>

      {/* Per-source table with 14d contribution bars */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[560px]">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-zinc-500 border-b border-zinc-800">
              <th className="text-left py-2 font-medium">Source</th>
              <th className="text-left py-2 font-medium">Type</th>
              <th className="text-left py-2 font-medium">Status</th>
              <th className="text-right py-2 font-medium">Jobs (14d)</th>
              <th className="text-left py-2 font-medium w-40">Contribution</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60">
            {sorted.map((s) => {
              const meta = SCHED_META[s.scheduling];
              return (
                <tr key={s.name} className="text-zinc-300">
                  <td className="py-2 capitalize font-medium text-zinc-100">{s.name}</td>
                  <td className="py-2 text-zinc-500 text-xs">{KIND_LABEL[s.kind]}</td>
                  <td className="py-2">
                    <span className={cn("inline-block text-[11px] px-1.5 py-0.5 rounded border", meta.cls)}>
                      {meta.label}
                    </span>
                    {s.flagged && s.flag_reason && (
                      <span className="ml-1.5 text-[10px] text-red-400/80">{s.flag_reason.replace(/_/g, " ")}</span>
                    )}
                  </td>
                  <td className="py-2 text-right tabular-nums text-zinc-300">{s.jobs_found || "—"}</td>
                  <td className="py-2">
                    <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                      <div className="h-full rounded-full bg-amber-500/60"
                        style={{ width: `${(s.jobs_found / maxJobs) * 100}%` }} />
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
