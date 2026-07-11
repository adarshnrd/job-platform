"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import type { DiscoveryEvent, DiscoveryRun, RecentDiscoveryJob } from "@/types";
import {
  Activity, Bot, CheckCircle2, Clock, Globe, HeartPulse, Loader2,
  MapPin, Search, Terminal, XCircle, Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import toast from "react-hot-toast";
import { AiUsagePanel } from "./ai-usage";
import { duration, timeAgo } from "./format";
import { RunLedger } from "./run-ledger";
import { SourceHealthPanel } from "./source-health";
import { CoverageSummaryPanel } from "./coverage-summary";

type Region = "india" | "global";
type Tab = "live" | "history" | "sources" | "ai";

const TABS: Array<{ key: Tab; label: string; icon: typeof Activity }> = [
  { key: "live",    label: "Live",           icon: Activity },
  { key: "history", label: "Run history",    icon: Clock },
  { key: "sources", label: "Source health",  icon: HeartPulse },
  { key: "ai",      label: "AI usage",       icon: Bot },
];

const STEPS: Array<{ key: string; label: string }> = [
  { key: "initializing", label: "Initializing" },
  { key: "searching",    label: "Searching" },
  { key: "analyzing",    label: "Analyzing" },
  { key: "scoring",      label: "Scoring" },
  { key: "saving",       label: "Saving" },
];

const WINDOWS = [
  { key: "10m", label: "10 min" },
  { key: "1h",  label: "1 hour" },
  { key: "24h", label: "24 hours" },
  { key: "7d",  label: "7 days" },
];

export function ActivityClient() {
  const [tab, setTab] = useState<Tab>("live");
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [active, setActive] = useState(false);
  const [events, setEvents] = useState<DiscoveryEvent[]>([]);
  const [recentWindow, setRecentWindow] = useState("1h");
  const [recent, setRecent] = useState<{ count: number; jobs: RecentDiscoveryJob[] } | null>(null);
  const [region, setRegion] = useState<Region>("india");
  const [starting, setStarting] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [, setClock] = useState(0); // re-render tick so elapsed time counts up

  const runIdRef = useRef<string | null>(null);
  const seqRef = useRef(0);
  const logRef = useRef<HTMLDivElement>(null);

  const poll = useCallback(async () => {
    try {
      const s = await api.discovery.status();
      setActive(s.active);
      setRun(s.run);
      if (s.run) {
        if (runIdRef.current !== s.run.run_id) {
          runIdRef.current = s.run.run_id;
          seqRef.current = 0;
          setEvents([]);
        }
        const ev = await api.discovery.events(s.run.run_id, seqRef.current);
        seqRef.current = ev.last_seq;
        if (ev.events.length) setEvents((prev) => [...prev, ...ev.events].slice(-500));
      }
    } catch {
      /* backend unreachable — keep last known state */
    } finally {
      setLoaded(true);
    }
  }, []);

  // Status + live log: fast poll while a run is active, slow when idle.
  useEffect(() => {
    poll();
    const iv = setInterval(poll, active ? 2000 : 8000);
    return () => clearInterval(iv);
  }, [active, poll]);

  // Elapsed-time ticker while running.
  useEffect(() => {
    if (!active) return;
    const iv = setInterval(() => setClock((c) => c + 1), 1000);
    return () => clearInterval(iv);
  }, [active]);

  // Recently discovered jobs for the selected window.
  const loadRecent = useCallback(async () => {
    try {
      const r = await api.discovery.recent(recentWindow);
      setRecent({ count: r.count, jobs: r.jobs });
    } catch { /* ignore */ }
  }, [recentWindow]);
  useEffect(() => {
    loadRecent();
    const iv = setInterval(loadRecent, 30000);
    return () => clearInterval(iv);
  }, [loadRecent, active]);

  // Keep the log pinned to the bottom unless the user scrolled up.
  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (nearBottom) el.scrollTop = el.scrollHeight;
  }, [events]);

  const startDiscovery = async () => {
    setStarting(true);
    try {
      const res = await api.jobs.discover({ region });
      toast.success(res.already_running ? "Already running — showing live progress" : "Discovery started");
      poll();
    } catch (e: any) {
      toast.error(e.message || "Failed to start discovery");
    } finally {
      setStarting(false);
    }
  };

  const stepIndex = run ? STEPS.findIndex((s) => s.key === run.phase) : -1;
  const sources = run ? Object.entries(run.sources) : [];
  const sourcesDone = sources.filter(([, s]) => s.status === "done" || s.status === "error").length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold flex items-center gap-2">
            <Activity size={20} className="text-amber-400" /> Search Activity
          </h1>
          <p className="text-sm text-zinc-400 mt-1">
            Live view of what the discovery engine is doing behind the scenes.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex rounded-lg border border-zinc-800 overflow-hidden">
            {(["india", "global"] as Region[]).map((r) => (
              <button key={r} onClick={() => setRegion(r)}
                className={cn(
                  "px-3 py-2 text-sm flex items-center gap-1.5 transition-colors",
                  region === r ? "bg-amber-500 text-black font-semibold" : "bg-zinc-900 text-zinc-400 hover:text-zinc-100"
                )}>
                {r === "india" ? <MapPin size={14} /> : <Globe size={14} />}
                {r === "india" ? "India" : "Global"}
              </button>
            ))}
          </div>
          <button onClick={startDiscovery} disabled={starting || active}
            className="btn-primary flex items-center gap-2">
            <Zap size={16} />
            {active ? "Running…" : starting ? "Starting…" : "Discover Jobs"}
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-zinc-800">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button key={key} onClick={() => setTab(key)}
            className={cn(
              "flex items-center gap-1.5 px-3.5 py-2 text-sm border-b-2 -mb-px transition-colors",
              tab === key
                ? "border-amber-500 text-amber-400 font-medium"
                : "border-transparent text-zinc-500 hover:text-zinc-200"
            )}>
            <Icon size={14} /> {label}
            {key === "live" && active && (
              <span className="relative flex h-1.5 w-1.5 ml-0.5">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-60" />
                <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-amber-500" />
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === "history" && <RunLedger />}
      {tab === "sources" && (
        <div className="space-y-6">
          <CoverageSummaryPanel />
          <SourceHealthPanel />
        </div>
      )}
      {tab === "ai" && <AiUsagePanel />}

      {/* Live run panel */}
      {tab !== "live" ? null : !loaded ? (
        <div className="card p-10 flex items-center justify-center text-zinc-500">
          <Loader2 size={18} className="animate-spin mr-2" /> Loading activity…
        </div>
      ) : !run ? (
        <div className="card p-10 text-center text-zinc-500">
          <Search size={28} className="mx-auto mb-3 text-zinc-600" />
          No discovery runs yet. Click <span className="text-amber-400 font-medium">Discover Jobs</span> to start
          searching — you&apos;ll see every step live here.
        </div>
      ) : (
        <div className="card p-5 space-y-5">
          {/* Run meta */}
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-3">
              {run.status === "running" ? (
                <span className="flex items-center gap-2 text-amber-400 text-sm font-semibold">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-60" />
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500" />
                  </span>
                  Discovery in progress
                </span>
              ) : run.status === "failed" ? (
                <span className="flex items-center gap-1.5 text-red-400 text-sm font-semibold">
                  <XCircle size={15} /> Last run failed
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-emerald-400 text-sm font-semibold">
                  <CheckCircle2 size={15} /> Last run completed
                </span>
              )}
              <span className="text-xs text-zinc-500">
                {run.trigger === "scheduled" ? "Scheduled" : "Manual"} · {run.region} · started {timeAgo(run.started_at)}
              </span>
            </div>
            <span className="flex items-center gap-1.5 text-xs text-zinc-400">
              <Clock size={13} /> {duration(run.started_at, run.finished_at)}
            </span>
          </div>

          {/* Phase stepper */}
          <div className="flex items-center">
            {STEPS.map((step, i) => {
              const done = run.status === "completed" || (stepIndex >= 0 && i < stepIndex);
              const current = run.status === "running" && i === stepIndex;
              const failedHere = run.status === "failed" && i === Math.max(stepIndex, 0);
              return (
                <div key={step.key} className="flex items-center flex-1 last:flex-none">
                  <div className="flex flex-col items-center gap-1.5">
                    <div className={cn(
                      "w-7 h-7 rounded-full flex items-center justify-center border text-[11px] font-bold",
                      done && "bg-emerald-500/15 border-emerald-500/50 text-emerald-400",
                      current && "bg-amber-500/15 border-amber-500/60 text-amber-400",
                      failedHere && "bg-red-500/15 border-red-500/50 text-red-400",
                      !done && !current && !failedHere && "bg-zinc-900 border-zinc-800 text-zinc-600"
                    )}>
                      {done ? <CheckCircle2 size={14} /> :
                        current ? <Loader2 size={14} className="animate-spin" /> :
                        failedHere ? <XCircle size={14} /> : i + 1}
                    </div>
                    <span className={cn(
                      "text-[10px] whitespace-nowrap",
                      current ? "text-amber-400 font-semibold" : done ? "text-emerald-500" : "text-zinc-500"
                    )}>{step.label}</span>
                  </div>
                  {i < STEPS.length - 1 && (
                    <div className={cn("h-px flex-1 mx-2 mb-4", done ? "bg-emerald-500/40" : "bg-zinc-800")} />
                  )}
                </div>
              );
            })}
          </div>

          {/* Current action line */}
          {run.status === "running" && (
            <div className="text-sm text-zinc-300 bg-zinc-900/70 border border-zinc-800 rounded-lg px-3 py-2 flex items-center gap-2">
              <Loader2 size={14} className="animate-spin text-amber-400 shrink-0" />
              {run.current_source ? (
                <span>
                  Searching <span className="text-amber-400 font-medium">{run.current_source}</span>
                  {run.current_query && <> for &quot;<span className="text-zinc-100">{run.current_query}</span>&quot;</>}…
                </span>
              ) : (
                <span className="capitalize">{run.phase}…</span>
              )}
            </div>
          )}
          {run.status === "failed" && run.error && (
            <div className="text-sm text-red-400 bg-red-500/5 border border-red-500/20 rounded-lg px-3 py-2">
              {run.error}
            </div>
          )}

          {/* Counters */}
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            {[
              { label: "Sources", value: `${sourcesDone}/${sources.length}` },
              { label: "Jobs found", value: run.counts.scraped },
              { label: "AI evaluated", value: run.counts.evaluated },
              { label: "Matched", value: run.counts.matched },
              { label: "Auto-queued", value: run.counts.queued },
            ].map((c) => (
              <div key={c.label} className="bg-zinc-900/70 border border-zinc-800 rounded-lg px-3 py-2.5">
                <div className="text-lg font-bold text-zinc-100">{c.value}</div>
                <div className="text-[11px] text-zinc-500">{c.label}</div>
              </div>
            ))}
          </div>

          {/* Per-source status */}
          {sources.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {sources.map(([name, s]) => (
                <span key={name} title={s.error || undefined}
                  className={cn(
                    "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs border",
                    s.status === "searching" && "border-amber-500/50 text-amber-400 bg-amber-500/10",
                    s.status === "done" && "border-emerald-500/40 text-emerald-400 bg-emerald-500/5",
                    s.status === "error" && "border-red-500/40 text-red-400 bg-red-500/5",
                    s.status === "pending" && "border-zinc-800 text-zinc-500 bg-zinc-900"
                  )}>
                  {s.status === "searching" ? <Loader2 size={11} className="animate-spin" /> :
                    s.status === "done" ? <CheckCircle2 size={11} /> :
                    s.status === "error" ? <XCircle size={11} /> : <Clock size={11} />}
                  {name}
                  {(s.status === "done" || s.jobs_found > 0) && (
                    <span className="font-semibold">{s.jobs_found}</span>
                  )}
                </span>
              ))}
            </div>
          )}

          {/* Live log */}
          <div>
            <div className="flex items-center gap-1.5 text-xs text-zinc-500 mb-2">
              <Terminal size={13} /> Live activity log
            </div>
            <div ref={logRef}
              className="bg-black/60 border border-zinc-800 rounded-lg p-3 h-64 overflow-y-auto font-mono text-[11.5px] leading-relaxed space-y-0.5">
              {events.length === 0 ? (
                <div className="text-zinc-600">Waiting for events…</div>
              ) : events.map((e) => (
                <div key={e.seq} className="flex gap-2">
                  <span className="text-zinc-600 shrink-0">
                    {new Date(e.ts).toLocaleTimeString([], { hour12: false })}
                  </span>
                  <span className={cn(
                    e.level === "error" ? "text-red-400" :
                    e.level === "success" ? "text-emerald-400" : "text-zinc-300"
                  )}>{e.message}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Recently discovered jobs */}
      {tab === "live" && (
      <div className="card p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold flex items-center gap-2">
            <Search size={15} className="text-amber-400" /> Recently discovered
            {recent && <span className="text-zinc-500 font-normal">— {recent.count} in the last {WINDOWS.find(w => w.key === recentWindow)?.label}</span>}
          </h2>
          <div className="flex rounded-lg border border-zinc-800 overflow-hidden">
            {WINDOWS.map((w) => (
              <button key={w.key} onClick={() => setRecentWindow(w.key)}
                className={cn(
                  "px-2.5 py-1.5 text-xs transition-colors",
                  recentWindow === w.key ? "bg-zinc-800 text-zinc-100 font-medium" : "bg-zinc-900 text-zinc-500 hover:text-zinc-200"
                )}>
                {w.label}
              </button>
            ))}
          </div>
        </div>
        {!recent || recent.jobs.length === 0 ? (
          <div className="text-sm text-zinc-500 py-6 text-center">
            No jobs discovered in this window.
          </div>
        ) : (
          <div className="divide-y divide-zinc-800/60 max-h-80 overflow-y-auto">
            {recent.jobs.map((j) => (
              <div key={j.id} className="py-2.5 flex items-center gap-3">
                <div className="flex-1 min-w-0">
                  <div className="text-sm text-zinc-100 truncate">{j.job_title}</div>
                  <div className="text-xs text-zinc-500 truncate">
                    {j.job_company}{j.job_location ? ` · ${j.job_location}` : ""}
                  </div>
                </div>
                <span className="text-[10px] uppercase tracking-wide text-zinc-500 bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5">
                  {j.source_platform}
                </span>
                {j.match_score != null && (
                  <span className={cn(
                    "text-xs font-bold w-10 text-right",
                    j.match_score >= 80 ? "text-emerald-400" : j.match_score >= 60 ? "text-amber-400" : "text-zinc-400"
                  )}>{j.match_score}%</span>
                )}
                <span className="text-xs text-zinc-600 w-16 text-right">{timeAgo(j.created_at)}</span>
              </div>
            ))}
          </div>
        )}
      </div>
      )}
    </div>
  );
}
