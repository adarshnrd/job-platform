"use client";
import { useEffect, useState } from "react";
import { createClient } from "@/lib/supabase/client";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, LineChart, Line } from "recharts";
import { Application } from "@/types";
import { STATUS_CONFIG } from "@/lib/utils";

const COLORS = ["#f59e0b", "#3b82f6", "#8b5cf6", "#22c55e", "#ef4444", "#06b6d4"];

export function AnalyticsClient({ userId }: { userId: string }) {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const supabase = createClient();

  useEffect(() => {
    supabase.from("application_details").select("*").eq("user_id", userId).then(({ data }) => {
      setApps(data || []);
      setLoading(false);
    });
  }, [userId]);

  if (loading) return <div className="flex items-center justify-center h-64 text-zinc-500">Loading analytics...</div>;

  // Status breakdown
  const statusData = Object.entries(
    apps.reduce((acc: Record<string, number>, a) => {
      acc[a.status] = (acc[a.status] || 0) + 1;
      return acc;
    }, {})
  ).map(([status, count]) => ({
    name: (STATUS_CONFIG as Record<string, { label: string }>)[status]?.label || status,
    value: count,
  }));

  // Platform breakdown
  const platformData = Object.entries(
    apps.reduce((acc: Record<string, number>, a) => {
      const p = a.source_platform || "other";
      acc[p] = (acc[p] || 0) + 1;
      return acc;
    }, {})
  ).map(([name, value]) => ({ name, value }));

  // Score distribution
  const scoreBuckets = [
    { range: "80-100", count: apps.filter(a => a.match_score >= 80).length },
    { range: "60-79", count: apps.filter(a => a.match_score >= 60 && a.match_score < 80).length },
    { range: "50-59", count: apps.filter(a => a.match_score >= 50 && a.match_score < 60).length },
    { range: "<50", count: apps.filter(a => a.match_score < 50).length },
  ];

  const applied = apps.filter(a => !["matched", "queued", "discovered"].includes(a.status)).length;
  const interviews = apps.filter(a => ["interview_scheduled", "technical_round", "hr_round"].includes(a.status)).length;
  const offers = apps.filter(a => ["offer_received", "accepted"].includes(a.status)).length;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Analytics</h1>

      {/* KPI cards */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: "Total Matched", value: apps.length, color: "text-blue-400" },
          { label: "Applications Sent", value: applied, color: "text-green-400" },
          { label: "Interview Rate", value: applied > 0 ? `${Math.round((interviews / applied) * 100)}%` : "—", color: "text-violet-400" },
          { label: "Offer Rate", value: interviews > 0 ? `${Math.round((offers / interviews) * 100)}%` : "—", color: "text-amber-400" },
        ].map(({ label, value, color }) => (
          <div key={label} className="card p-5">
            <p className="text-xs text-zinc-500 mb-1">{label}</p>
            <p className={`text-3xl font-bold font-mono ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-6">
        {/* Status breakdown */}
        <div className="card p-5">
          <h2 className="font-semibold mb-4 text-sm">Status Breakdown</h2>
          <ResponsiveContainer width="100%" height={200}>
            <PieChart>
              <Pie data={statusData} cx="50%" cy="50%" innerRadius={50} outerRadius={80} dataKey="value" label={({ name, value }) => `${name}: ${value}`} labelLine={false} fontSize={10}>
                {statusData.map((_, i) => <Cell key={i} fill={COLORS[i % COLORS.length]} />)}
              </Pie>
              <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8 }} />
            </PieChart>
          </ResponsiveContainer>
        </div>

        {/* Match score distribution */}
        <div className="card p-5">
          <h2 className="font-semibold mb-4 text-sm">Match Score Distribution</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={scoreBuckets} barSize={40}>
              <XAxis dataKey="range" tick={{ fill: "#71717a", fontSize: 12 }} axisLine={false} tickLine={false} />
              <YAxis tick={{ fill: "#71717a", fontSize: 12 }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8 }} />
              <Bar dataKey="count" fill="#f59e0b" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Platform breakdown */}
        <div className="card p-5 col-span-2">
          <h2 className="font-semibold mb-4 text-sm">Applications by Platform</h2>
          <ResponsiveContainer width="100%" height={160}>
            <BarChart data={platformData} layout="vertical" barSize={20}>
              <XAxis type="number" tick={{ fill: "#71717a", fontSize: 12 }} axisLine={false} tickLine={false} />
              <YAxis dataKey="name" type="category" width={90} tick={{ fill: "#a1a1aa", fontSize: 12 }} axisLine={false} tickLine={false} />
              <Tooltip contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8 }} />
              <Bar dataKey="value" fill="#3b82f6" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
