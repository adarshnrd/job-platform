import { PipelineStats } from "@/types";
import { Briefcase, Target, MessageSquare, TrendingUp } from "lucide-react";

export function StatsRow({ stats }: { stats: PipelineStats }) {
  const cards = [
    { icon: Briefcase, label: "Applied", value: stats.total_applied, color: "text-green-400" },
    { icon: Target, label: "Matched", value: stats.total_matched, color: "text-blue-400" },
    { icon: MessageSquare, label: "Interviews", value: stats.active_interviews, color: "text-violet-400" },
    { icon: TrendingUp, label: "Avg Match", value: `${stats.avg_match_score}%`, color: "text-amber-400" },
  ];

  return (
    <div className="grid grid-cols-4 gap-4">
      {cards.map(({ icon: Icon, label, value, color }) => (
        <div key={label} className="card p-4 flex items-center gap-3">
          <div className={`p-2 rounded-lg bg-zinc-800 ${color}`}>
            <Icon size={16} />
          </div>
          <div>
            <p className="text-xs text-zinc-500">{label}</p>
            <p className={`text-xl font-bold font-mono ${color}`}>{value}</p>
          </div>
        </div>
      ))}
    </div>
  );
}
