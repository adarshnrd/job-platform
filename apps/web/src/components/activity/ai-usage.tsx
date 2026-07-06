"use client";
import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AiUsageSummary } from "@/types";
import { AlertTriangle, Bot, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { fmtCost, fmtTokens } from "./format";

function BucketTable({ title, buckets }: { title: string; buckets: AiUsageSummary["providers"] }) {
  const rows = Object.entries(buckets);
  return (
    <div className="flex-1 min-w-[260px]">
      <div className="text-[11px] uppercase tracking-wide text-zinc-500 mb-2">{title}</div>
      {rows.length === 0 ? (
        <div className="text-xs text-zinc-600 py-2">No calls today.</div>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-[10px] uppercase tracking-wide text-zinc-600 border-b border-zinc-800">
              <th className="text-left py-1.5 font-medium">Name</th>
              <th className="text-right py-1.5 font-medium">Calls</th>
              <th className="text-right py-1.5 font-medium">In</th>
              <th className="text-right py-1.5 font-medium">Out</th>
              <th className="text-right py-1.5 font-medium">Cost</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/60">
            {rows.map(([name, b]) => (
              <tr key={name} className="text-zinc-300">
                <td className="py-1.5">{name.replace(/_/g, " ")}</td>
                <td className="py-1.5 text-right text-zinc-400">{b.calls}</td>
                <td className="py-1.5 text-right text-zinc-400">{fmtTokens(b.input_tokens)}</td>
                <td className="py-1.5 text-right text-zinc-400">{fmtTokens(b.output_tokens)}</td>
                <td className="py-1.5 text-right">{fmtCost(b.cost_usd)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function AiUsagePanel() {
  const [data, setData] = useState<AiUsageSummary | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await api.telemetry.aiUsage(14));
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    load();
    const iv = setInterval(load, 30000);
    return () => clearInterval(iv);
  }, [load]);

  if (failed) {
    return <div className="card p-6 text-sm text-zinc-500 text-center">Could not load AI usage.</div>;
  }
  if (!data) {
    return (
      <div className="card p-8 flex items-center justify-center text-zinc-500">
        <Loader2 size={16} className="animate-spin mr-2" /> Loading AI usage…
      </div>
    );
  }

  const { budget, today } = data;
  const tokenPct = budget.token_budget ? Math.min(100, (budget.tokens_used / budget.token_budget) * 100) : null;
  const costPct = budget.usd_budget ? Math.min(100, (budget.cost_used / budget.usd_budget) * 100) : null;
  const maxDaily = Math.max(1, ...data.daily.map((d) => d.tokens));

  return (
    <div className="space-y-4">
      {budget.exceeded && (
        <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
          <AlertTriangle size={16} className="shrink-0" />
          Daily LLM budget exhausted — all AI calls are blocked until midnight UTC. Scoring and discovery will skip AI steps.
        </div>
      )}

      <div className="card p-5 space-y-5">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Bot size={15} className="text-amber-400" /> AI usage today
        </h2>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: "Calls", value: today.calls },
            { label: "Input tokens", value: fmtTokens(today.input_tokens) },
            { label: "Output tokens", value: fmtTokens(today.output_tokens) },
            { label: "Est. cost", value: fmtCost(today.cost_usd) },
          ].map((c) => (
            <div key={c.label} className="bg-zinc-900/70 border border-zinc-800 rounded-lg px-3 py-2.5">
              <div className="text-lg font-bold text-zinc-100">{c.value}</div>
              <div className="text-[11px] text-zinc-500">{c.label}</div>
            </div>
          ))}
        </div>

        {tokenPct === null && costPct === null ? (
          <div className="text-[11px] text-zinc-600">
            No daily budget configured — set <code className="text-zinc-400">LLM_DAILY_TOKEN_BUDGET</code> or{" "}
            <code className="text-zinc-400">LLM_DAILY_BUDGET_USD</code> in the backend <code className="text-zinc-400">.env</code> to
            enable a hard stop.
          </div>
        ) : (
          <div className="space-y-2.5">
            {tokenPct !== null && (
              <div>
                <div className="flex justify-between text-[11px] text-zinc-500 mb-1">
                  <span>Token budget</span>
                  <span>{fmtTokens(budget.tokens_used)} / {fmtTokens(budget.token_budget)}</span>
                </div>
                <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                  <div className={cn("h-full rounded-full", tokenPct >= 100 ? "bg-red-500" : tokenPct >= 80 ? "bg-amber-500" : "bg-emerald-500")}
                    style={{ width: `${tokenPct}%` }} />
                </div>
              </div>
            )}
            {costPct !== null && (
              <div>
                <div className="flex justify-between text-[11px] text-zinc-500 mb-1">
                  <span>Cost budget</span>
                  <span>{fmtCost(budget.cost_used)} / {fmtCost(budget.usd_budget)}</span>
                </div>
                <div className="h-1.5 rounded-full bg-zinc-800 overflow-hidden">
                  <div className={cn("h-full rounded-full", costPct >= 100 ? "bg-red-500" : costPct >= 80 ? "bg-amber-500" : "bg-emerald-500")}
                    style={{ width: `${costPct}%` }} />
                </div>
              </div>
            )}
          </div>
        )}

        <div className="flex flex-wrap gap-8">
          <BucketTable title="By provider" buckets={data.providers} />
          <BucketTable title="By feature" buckets={data.features} />
        </div>
      </div>

      <div className="card p-5">
        <div className="text-[11px] uppercase tracking-wide text-zinc-500 mb-3">Tokens per day — last 14 days</div>
        <div className="flex items-end gap-1.5 h-24">
          {data.daily.map((d) => (
            <div key={d.day} className="flex-1 flex flex-col items-center gap-1 group" title={`${d.day}: ${fmtTokens(d.tokens)} tokens · ${d.calls} calls · ${fmtCost(d.cost_usd)}`}>
              <div className="w-full rounded-t bg-amber-500/50 group-hover:bg-amber-400 transition-colors"
                style={{ height: `${Math.max(d.tokens > 0 ? 4 : 1, (d.tokens / maxDaily) * 80)}px` }} />
              <span className="text-[9px] text-zinc-600">{d.day.slice(8)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
